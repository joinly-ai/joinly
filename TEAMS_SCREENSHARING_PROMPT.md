# Teams Screen Sharing Implementation

Enable screen sharing for Teams meetings. Apply changes **incrementally** — test after each phase and only proceed to the next if the test fails.

## Root Cause

Playwright's bundled Chromium on Linux lacks H.264 codec support (only VP8/VP9/AV1). Teams requires H.264 for video — the Teams calling SDK checks `RTCRtpSender.getCapabilities('video')`, finds no H.264, and tells the server not to allocate video transceivers. The server responds with SDP `BUNDLE` containing only audio + data (all video m-lines set to `port=0`).

## How to Test Each Phase

After each phase, write a test script that:
1. Starts the full service stack (PulseServer, DbusSession, VirtualDisplay, VirtualSpeaker, VirtualMicrophone, BrowserSession)
2. Creates a page and navigates to a Teams meeting URL (passed as CLI arg)
3. Installs an SDP monitor via `page.add_init_script()` BEFORE navigating — it wraps `RTCPeerConnection.prototype.setRemoteDescription` to log BUNDLE and m-lines via `console.log('[joinly-sdp] ...')`
4. Fills the name field, clicks Join, waits for admission (check for "leave" button visibility)
5. After admission, waits 20s, then logs the SDP data

**Success criteria**: The SDP log shows:
```
[joinly-sdp] setRemoteDescription type=offer m-lines=13 BUNDLE=["a=group:BUNDLE 1 2 ..."]
  m=video 3480 UDP/TLS/RTP/SAVPF 107 99    ← H.264, port NOT 0
```

**Failure**: BUNDLE has only 2 entries, and/or all `m=video` lines have `port=0`.

Also confirm H.264 is available in the browser:
```js
RTCRtpSender.getCapabilities('video').codecs.filter(c => c.mimeType.includes('264'))
// Should return 6 H.264 profiles
```

---

## Phase 1: System Chromium (H.264 codec fix)

**This is the essential fix. Everything else may be unnecessary.**

### 1a. `joinly/providers/browser/browser_session.py`

Prefer the system Chromium binary (which has H.264 via OpenH264) over Playwright's bundled Chromium.

- Add `import shutil` to imports
- Add a module-level constant: `_SYSTEM_CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser")`
- In `__aenter__`, replace the line `bin_path = Path(self._playwright.chromium.executable_path)` with logic that checks `_SYSTEM_CHROMIUM` first. If found, use it with an INFO log. Otherwise fall back to Playwright's path with a WARNING log.
- Remove the `--test-type` flag from the Chromium launch args (it's a headless detection signal)
- Add `--disable-hang-monitor` and `--disable-prompt-on-repost` flags

### 1b. Dockerfiles (`docker/Dockerfile`, `docker/Dockerfile.lite`, `docker/Dockerfile.cuda`)

Add `chromium` to the `apt-get install` list in all three Dockerfiles. Add a comment:
```
# NOTE: The system chromium package is required for H.264 codec support
# (via OpenH264). Playwright's bundled Chromium lacks H.264 on Linux ARM64,
# which prevents Teams from allocating video transceivers.
```

### 1c. TEST

Run the test script. If the SDP shows all 13 m-lines with video on non-zero ports, **skip Phase 2 and Phase 3 entirely** — go straight to Phase 4 (screen capture implementation).

---

## Phase 2: Signaling Interceptor (only if Phase 1 SDP shows port=0)

If Phase 1 alone doesn't get video allocated, the server still restricts capabilities for anonymous guests. This phase patches the signaling to force-enable video and screen sharing.

### 2a. `joinly/providers/browser/meeting_provider.py`

Add `CDPSession` to the playwright imports. Add `self._signaling_cdp: CDPSession | None = None` instance variable.

Before calling `controller.join()` in the `join()` method, add a Teams-specific block that calls `_install_signaling_interceptor(self._page)`.

#### `_install_signaling_interceptor(page)` — new async method

Uses CDP `Fetch.enable` to intercept all requests/responses to `*conv.skype.com*`, `*flightproxy*`, `*broker.skype.com*` at both Request and Response stages.

**Request stage** — patch outgoing JSON bodies:
- `clientEndpointCapabilities |= 4` and `endpointCapabilities |= 4` (bit 2 = ScreenSharing)
- Append `"ScreenSharing"` to `callModalities` and `mediaTypesToUse` lists if missing
- Same for nested `mediaAnswer.callModalities`, `mediaNegotiation.callModalities`, `mediaOffer.callModalities`
- Use `Fetch.continueRequest` with modified postData (base64-encoded)

**Response stage** — patch incoming server JSON:
- Set `meetingDetails.meetingCapability.allowIPVideo = True`
- Add ScreenSharing bit to all participants' `endpointCapabilities` in the roster
- Patch `mediaAnswer/mediaNegotiation/mediaOffer.callModalities` to include ScreenSharing
- If patched, use `Fetch.fulfillRequest` with modified body. Otherwise `Fetch.continueResponse`.
- **Critical**: Always ensure every intercepted request is continued/fulfilled — never stall the network stack. Wrap everything in try/except and always call continueResponse in the fallback.

### 2b. TEST

Run the test script again. If the SDP now shows video on non-zero ports, **skip Phase 3** — go to Phase 4.

---

## Phase 3: Platform Spoof (only if Phase 2 SDP still shows port=0)

If the server still rejects video even with patched capabilities, it may be filtering based on the `os=linux` identity sent in HTTP headers and WebSocket handshakes.

### 3a. `joinly/providers/browser/meeting_provider.py`

#### `_setup_teams_platform_spoof(page)` — new method

Uses CDP `Network.setUserAgentOverride` to make the browser appear as Chrome 133 on macOS 10.15.7. Sets:
- User-Agent: `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36`
- Platform: `"MacIntel"`
- Full Client Hints metadata (brands for Google Chrome 133, platform "macOS", platformVersion "10.15.7", architecture "x86", bitness "64", mobile false)

Store the CDP session in `self._signaling_cdp` for reuse by the signaling interceptor.

#### Header patching in the signaling interceptor

Add header rewriting to the request stage of the signaling interceptor:
- `X-Microsoft-Skype-Client`: replace `os=linux` → `os=macos`, `osVer=undefined` → `osVer=10.15.7`
- `sec-ch-ua-platform`: replace linux → `"macOS"`
- `User-Agent`: replace HeadlessChrome/Linux → the Chrome 133 macOS UA
- `sec-ch-ua`: replace with Google Chrome branded string

Return `list[dict]` of `{"name": ..., "value": ...}` for CDP Fetch headers.

### 3b. `joinly/providers/browser/platforms/teams.py`

Since the platform spoof makes us look like macOS Chrome, Teams shows a "Open Teams app" interstitial page. To bypass it:

- Add `import urllib.parse`
- Add a `to_v2_url(url)` static method: `https://teams.microsoft.com/v2/#{path}?{query}&anon=true`
- Call it from `join()` in meeting_provider.py before navigation (only for non-gov Teams URLs)

### 3c. TEST

Run the test script. The SDP should now show video allocated.

---

## Phase 4: Screen Capture Implementation (always needed)

Once the SDP has video m-lines allocated (from whichever phase succeeded), implement the actual screen capture. This provides the video stream when the user clicks Share.

### 4a. `joinly/providers/browser/platforms/teams.py` — share_screen improvements

- In `share_screen`, after clicking the share button, handle the share tray: look for a "Screen" or "Entire screen" button/menuitem and click it if visible (3s timeout). If no tray appears, continue — the share button directly triggers getDisplayMedia.
- In `_check_joined`, increase timeout from 10s to 20s and add two more lobby indicators: `"span >> text=/waiting/i"` and `"span >> text=/someone in the meeting/i"`
- Increase join button timeout from 1000ms to 10000ms

### 4b. `joinly/providers/browser/meeting_provider.py` — GDM interceptor + tab capture

#### `_install_gdm_interceptor(page)` — init script (add_init_script, runs BEFORE Teams JS)

Sets up plumbing for the later getDisplayMedia override:

1. **SDP monitor**: Wraps `RTCPeerConnection.prototype.setRemoteDescription` to log BUNDLE and m-lines via `console.log('[joinly-sdp] ...')`
2. **Symbol-based store**: Creates `Symbol.for('__joinly__')` on `navigator.mediaDevices` (non-enumerable) holding: `gdmHandler`, `overrideInstalled`, `origGDM`, `nativeStrings`
3. **toString stealth**: Overrides `Function.prototype.toString` with a Map-based lookup so overrides return `"function X() { [native code] }"` strings

**Important**: Do NOT override `enumerateDevices` or `getUserMedia` — fake camera causes Teams v2 to hang on "Connecting…". Leave `getDisplayMedia` completely native during init so the SDK sees it as native when calculating capabilities. The GDM override is installed later at share time only.

Call this from the Teams pre-join block in `join()`, before navigation.

#### `_setup_teams_tab_capture(page)` — called at share time (no content URL)

Installs the `getDisplayMedia` override using the Symbol store from init:

1. Creates a new `getDisplayMedia` function that delegates to the store's `gdmHandler`
2. Stealth: sets `.name`, `.length`, and adds to the toString Map
3. Replaces `MediaDevices.prototype.getDisplayMedia` with the override
4. Sets the handler: waits 2s (for signaling), tries tab self-capture (`selfBrowserSurface: 'include'`, `video: {displaySurface: 'browser'}`), falls back to canvas `captureStream(15)`, patches `track.getSettings()` to report `displaySurface: 'monitor'`

#### `_setup_teams_content_overlay(meeting_page, content_page)` — called at share time (with content URL)

Like above but also:
- Starts CDP `Page.startScreencast` on content_page
- Creates a canvas overlay on meeting_page
- Pumps screencast frames into the canvas via `__pushFrame(b64)`
- The GDM handler tries tab self-capture (which captures the overlay), falls back to `canvas.captureStream(15)`

#### Update `share_screen()` routing

In the `share_screen` method, add Teams-specific branching:
- If Teams + content_page → `_setup_teams_content_overlay`
- If Teams + no content_page → `_setup_teams_tab_capture`
- Otherwise → existing methods

#### Update `_remove_share_overlay()` cleanup

Add cleanup for the Symbol store: reset `gdmHandler` to null, `overrideInstalled` to false. Clear `window.__canvasRepaintId` interval. Close `window.__audioCtx` if present.

### 4c. Minor: `joinly/providers/browser/devices/virtual_display.py`

Add `-noxdamage` flag to the x11vnc command args (prevents X damage extension errors on aarch64). Not strictly related to screen sharing but good to include.

---

## Summary

| Phase | What | When to skip |
|-------|------|-------------|
| **1** | System Chromium for H.264 | Never — always needed |
| **2** | Signaling interceptor | Skip if Phase 1 test passes |
| **3** | Platform spoof + v2 URL | Skip if Phase 2 test passes |
| **4** | Screen capture implementation | Never — always needed for actual sharing |

The minimum viable change might be just Phase 1 + Phase 4. Test to find out.
