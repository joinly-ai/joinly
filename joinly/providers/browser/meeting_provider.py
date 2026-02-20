import asyncio
import io
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Self

from PIL import Image, ImageOps
from playwright.async_api import CDPSession, Page

from joinly.core import AudioReader, AudioWriter, VideoReader
from joinly.providers.base import BaseMeetingProvider
from joinly.providers.browser.browser_session import BrowserSession
from joinly.providers.browser.devices.dbus_session import DbusSession
from joinly.providers.browser.devices.pulse_server import PulseServer
from joinly.providers.browser.devices.virtual_display import VirtualDisplay
from joinly.providers.browser.devices.virtual_microphone import VirtualMicrophone
from joinly.providers.browser.devices.virtual_speaker import VirtualSpeaker
from joinly.providers.browser.platforms import (
    BrowserPlatformController,
    GoogleMeetBrowserPlatformController,
    TeamsBrowserPlatformController,
    ZoomBrowserPlatformController,
)
from joinly.settings import get_settings
from joinly.types import (
    AudioChunk,
    MeetingChatHistory,
    MeetingParticipant,
    ProviderNotSupportedError,
    VideoSnapshot,
)

logger = logging.getLogger(__name__)

PLATFORMS: list[type[BrowserPlatformController]] = [
    GoogleMeetBrowserPlatformController,
    TeamsBrowserPlatformController,
    ZoomBrowserPlatformController,
]


class _SpeakerInjectedAudioReader(AudioReader):
    """Audio reader that injects audio into the virtual speaker."""

    def __init__(
        self, reader: AudioReader, get_reader: Callable[[], str | None]
    ) -> None:
        """Initialize the audio reader with the virtual speaker."""
        self._reader = reader
        self._get_reader = get_reader
        self.audio_format = reader.audio_format

    async def read(self) -> AudioChunk:
        """Read audio data and inject it into the virtual speaker."""
        chunk = await self._reader.read()
        return AudioChunk(
            data=chunk.data,
            time_ns=chunk.time_ns,
            speaker=self._get_reader(),
        )


class BrowserMeetingProvider(BaseMeetingProvider, VideoReader):
    """A meeting provider that uses a web browser to join meetings."""

    def __init__(
        self,
        *,
        reader_byte_depth: int | None = None,
        writer_byte_depth: int | None = None,
        snapshot_size: tuple[int, int] = (512, 288),
        vnc_server: bool = False,
        vnc_server_port: int = 5900,
    ) -> None:
        """Initialize the browser meeting provider.

        Args:
            reader_byte_depth (int | None): The byte depth for the virtual speaker
                (default is None).
            writer_byte_depth (int | None): The byte depth for the virtual
                microphone (default is None).
            snapshot_size (tuple[int, int]): The size of the video snapshot
                (default is (512, 288)).
            vnc_server (bool): Whether to start a VNC server for the virtual display.
            vnc_server_port (int): The port to use for the VNC server.
        """
        self.snapshot_size = snapshot_size
        self._env = os.environ.copy()
        self._pulse_server = PulseServer(env=self._env)
        self._dbus_session = DbusSession(env=self._env)
        self._virtual_display = VirtualDisplay(
            env=self._env, use_vnc_server=vnc_server, vnc_port=vnc_server_port
        )
        self._virtual_speaker = (
            VirtualSpeaker(env=self._env)
            if not reader_byte_depth
            else VirtualSpeaker(env=self._env, byte_depth=reader_byte_depth)
        )
        self._virtual_microphone = (
            VirtualMicrophone(env=self._env)
            if not writer_byte_depth
            else VirtualMicrophone(env=self._env, byte_depth=writer_byte_depth)
        )
        self._browser_session = BrowserSession(env=self._env)
        self._services = [
            self._pulse_server,
            self._dbus_session,
            self._virtual_display,
            self._virtual_speaker,
            self._virtual_microphone,
            self._browser_session,
        ]

        self._page: Page | None = None
        self._content_page: Page | None = None
        self._is_sharing: bool = False
        self._platform_controller: BrowserPlatformController | None = None
        self._signaling_cdp: CDPSession | None = None
        self._stack = AsyncExitStack()
        self._lock = asyncio.Lock()

        self._speaker_injected_virtual_speaker = _SpeakerInjectedAudioReader(
            self._virtual_speaker,
            lambda: (
                self._platform_controller.active_speaker
                if self._platform_controller
                else None
            ),
        )

    @property
    def audio_reader(self) -> AudioReader:
        """Get the audio reader."""
        return self._speaker_injected_virtual_speaker

    @property
    def audio_writer(self) -> AudioWriter:
        """Get the audio writer."""
        return self._virtual_microphone

    @property
    def video_reader(self) -> VideoReader:
        """Get the video reader."""
        return self

    async def __aenter__(self) -> Self:
        """Enter the context manager."""
        try:
            for service in self._services:
                await self._stack.enter_async_context(service)

        except Exception:
            await self._stack.aclose()
            raise

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the context."""
        try:
            if self._page is not None and not self._page.is_closed():
                await self.leave()
        finally:
            await self._stack.aclose()

    @asynccontextmanager
    async def _action_guard(
        self, action: str
    ) -> AsyncIterator[tuple[Page, BrowserPlatformController]]:
        """Context manager to guard actions with a lock and error handling.

        Args:
            action: The action being guarded, for logging (e.g., "join", "leave", etc.).

        Yields:
            A tuple containing the current Page and the platform-specific controller.
        """
        if (
            self._page is None
            or self._page.is_closed()
            or self._platform_controller is None
        ):
            msg = f"Failed to perform '{action}'. Currently not in a meeting."
            logger.error(msg)
            raise RuntimeError(msg)

        async with self._lock:
            try:
                yield self._page, self._platform_controller
            except Exception as e:
                msg = f"Failed to perform '{action}'."
                logger.exception(msg)
                if isinstance(e, (ProviderNotSupportedError, ValueError)):
                    raise
                raise RuntimeError(msg) from None
            else:
                logger.info("Successfully performed '%s'.", action)

    async def _get_platform_controller(self, url: str) -> BrowserPlatformController:
        """Get the platform-specific meeting controller based on the URL.

        Args:
            url: The URL of the meeting.

        Returns:
            The platform-specific meeting controller.

        Raises:
            RuntimeError: If no matching platform controller is found for the URL.
        """
        for platform_controller_type in PLATFORMS:
            if platform_controller_type.url_pattern.match(url):
                return platform_controller_type()

        msg = (
            f"No supported platform found for URL: {url}. "
            "Supported platforms: "
            f"{
                ', '.join(
                    pc.__name__.removesuffix('BrowserPlatformController')
                    for pc in PLATFORMS
                )
            }."
        )
        raise RuntimeError(msg)

    async def _cleanup_content_page(self) -> None:
        """Close the content page if it exists and reset sharing state."""
        if self._content_page and not self._content_page.is_closed():
            await self._content_page.close()
        self._content_page = None
        self._is_sharing = False

    async def join(
        self,
        url: str | None = None,
        name: str | None = None,
        passcode: str | None = None,
    ) -> None:
        """Join a meeting.

        Args:
            url: The URL of the meeting to join.
            name: The name of the participant. If None, uses the default name from
                settings.
            passcode: The password or passcode for the meeting (if required).
        """
        if not url:
            msg = "Meeting URL is required to join a meeting."
            logger.error(msg)
            raise ValueError(msg)

        if self._page is not None and not self._page.is_closed():
            msg = "Meeting already joined. Leave the meeting before joining a new one."
            logger.error(msg)
            raise RuntimeError(msg)

        self._page = await self._browser_session.get_page()
        try:
            self._platform_controller = await self._get_platform_controller(url)
        except RuntimeError:
            await self._page.close()
            self._page = None
            raise

        if name is None:
            name = get_settings().name

        # For Teams, install the platform spoof, media-device interceptors
        # and signaling interceptor BEFORE the page loads.
        if isinstance(self._platform_controller, TeamsBrowserPlatformController):
            await self._setup_teams_platform_spoof(self._page)
            await self._install_gdm_interceptor(self._page)
            await self._install_signaling_interceptor(self._page)
            # Use v2 URL to bypass the app-launcher interstitial that
            # appears when the (now spoofed) User-Agent looks like macOS.
            if "teams.microsoft.us" not in url:
                url = TeamsBrowserPlatformController.to_v2_url(url)

        async with self._action_guard("join") as (page, controller):
            try:
                await controller.join(page, url, name=name, passcode=passcode)
            except Exception:
                await self._page.close()
                self._page = None
                self._platform_controller = None
                raise

    async def leave(self) -> None:
        """Leave the current meeting."""
        async with self._action_guard("leave") as (page, controller):
            try:
                if self._is_sharing:
                    await self._cleanup_content_page()
                    await page.bring_to_front()
                await controller.leave(page)
            except RuntimeError:
                logger.warning(
                    "Failed to leave the meeting, forcing page close.", exc_info=True
                )
            finally:
                self._platform_controller = None
                await self._cleanup_content_page()
                if self._page is not None and not self._page.is_closed():
                    await self._page.close()
                self._page = None

    async def send_chat_message(self, message: str) -> None:
        """Send a chat message in the meeting.

        Args:
            message: The message to send.
        """
        async with self._action_guard("send_chat_message") as (page, controller):
            await controller.send_chat_message(page, message)

    async def get_chat_history(self) -> MeetingChatHistory:
        """Get the chat history from the meeting.

        Returns:
            MeetingChatHistory: The chat history of the meeting.
        """
        async with self._action_guard("get_chat_history") as (page, controller):
            return await controller.get_chat_history(page)

    async def get_participants(self) -> list[MeetingParticipant]:
        """Get the list of participants in the meeting.

        Returns:
            list[MeetingParticipant]: A list of participants in the meeting.
        """
        async with self._action_guard("get_participants") as (page, controller):
            return await controller.get_participants(page)

    async def mute(self) -> None:
        """Mute yourself in the meeting."""
        async with self._action_guard("mute") as (page, controller):
            await controller.mute(page)

    async def unmute(self) -> None:
        """Unmute yourself in the meeting."""
        async with self._action_guard("unmute") as (page, controller):
            await controller.unmute(page)

    async def _setup_teams_platform_spoof(self, page: Page) -> None:
        """Make the browser appear as Google Chrome on macOS for Teams.

        Uses CDP ``Network.setUserAgentOverride`` to set the User-Agent,
        platform, and Client Hints metadata at the **browser engine**
        level.  This affects ALL HTTP requests (not just signaling) and
        all JavaScript APIs (``navigator.userAgent``,
        ``navigator.platform``, ``navigator.userAgentData``).

        Combined with the v2 meeting URL (set in ``join()``) to bypass
        the macOS/Windows app-launcher interstitial.
        """
        cdp = await page.context.new_cdp_session(page)
        self._signaling_cdp = cdp

        await cdp.send(
            "Network.setUserAgentOverride",
            {
                "userAgent": self._CHROME_UA,
                "platform": "MacIntel",
                "userAgentMetadata": {
                    "brands": [
                        {"brand": "Google Chrome", "version": "133"},
                        {"brand": "Chromium", "version": "133"},
                        {"brand": "Not_A Brand", "version": "24"},
                    ],
                    "fullVersionList": [
                        {
                            "brand": "Google Chrome",
                            "version": "133.0.0.0",
                        },
                        {"brand": "Chromium", "version": "133.0.0.0"},
                        {
                            "brand": "Not_A Brand",
                            "version": "24.0.0.0",
                        },
                    ],
                    "fullVersion": "133.0.0.0",
                    "platform": "macOS",
                    "platformVersion": "10.15.7",
                    "architecture": "x86",
                    "model": "",
                    "mobile": False,
                    "bitness": "64",
                    "wow64": False,
                },
            },
        )

    async def _install_gdm_interceptor(self, page: Page) -> None:
        """Install stealth getDisplayMedia plumbing before page scripts run.

        Uses ``add_init_script`` to set up:

        - A non-enumerable Symbol store on ``navigator.mediaDevices``
          for the ``getDisplayMedia`` handler (installed at share time).
        - ``Function.prototype.toString`` patching so any future
          overrides look native.
        - An SDP monitor on ``RTCPeerConnection.setRemoteDescription``
          for diagnostic logging.

        ``enumerateDevices`` and ``getUserMedia`` are **not** overridden
        — the fake camera caused the Teams v2 pre-join page to hang on
        "Connecting…".  Capability injection is handled by the signaling
        interceptor instead.
        """
        await page.add_init_script(
            """(() => {
            /* --- RTCPeerConnection SDP monitor --- */
            const _origSetRemote = RTCPeerConnection.prototype.setRemoteDescription;
            RTCPeerConnection.prototype.setRemoteDescription = function(desc) {
                if (desc && desc.sdp) {
                    const lines = desc.sdp.split('\\r\\n');
                    const bundle = lines.filter(l => l.startsWith('a=group:BUNDLE'));
                    const mlines = lines.filter(l => l.startsWith('m='));
                    console.log('[joinly-sdp] setRemoteDescription type=' + desc.type
                        + ' m-lines=' + mlines.length
                        + ' BUNDLE=' + JSON.stringify(bundle));
                    mlines.forEach(m => console.log('[joinly-sdp]   ' + m));
                }
                return _origSetRemote.apply(this, arguments);
            };

            const md = navigator.mediaDevices;
            if (!md) return;

            const _sym = Symbol.for('__joinly__');

            /* ---- Internal store (non-enumerable) ---- */
            const store = {
                gdmHandler: null,
                overrideInstalled: false,
                origGDM: MediaDevices.prototype.getDisplayMedia || null,
                nativeStrings: null,
            };
            Object.defineProperty(md, _sym, {
                value: store,
                writable: false,
                enumerable: false,
                configurable: false,
            });

            /* ---- toString stealth ---- */
            const origToString = Function.prototype.toString;
            const nativeStrings = new Map();
            store.nativeStrings = nativeStrings;

            const newToString = function toString() {
                if (nativeStrings.has(this))
                    return nativeStrings.get(this);
                return origToString.call(this);
            };
            nativeStrings.set(newToString,
                'function toString() { [native code] }');
            Object.defineProperty(newToString, 'name',
                {value: 'toString', configurable: true});
            Object.defineProperty(newToString, 'length',
                {value: 0, configurable: true});
            Function.prototype.toString = newToString;

            })();"""
        )

    @staticmethod
    def _patch_screensharing_fields(body: dict) -> bool:  # type: ignore[type-arg]
        """Add ScreenSharing to capability fields in a signaling body.

        Returns ``True`` if any field was modified.
        """
        patched = False

        # clientEndpointCapabilities |= 4 (bit 2 = ScreenSharing)
        for cap_key in ("clientEndpointCapabilities", "endpointCapabilities"):
            val = body.get(cap_key)
            if val is not None and not (int(val) & 4):
                body[cap_key] = int(val) | 4
                patched = True
                logger.debug("Patched %s: %s → %s", cap_key, val, body[cap_key])

        # Top-level list fields
        for list_key in ("callModalities", "mediaTypesToUse"):
            lst = body.get(list_key)
            if isinstance(lst, list) and "ScreenSharing" not in lst:
                lst.append("ScreenSharing")
                patched = True
                logger.debug("Patched %s: %s", list_key, lst)

        # Nested wrappers (mediaAnswer, mediaNegotiation, mediaOffer)
        for wrapper in ("mediaAnswer", "mediaNegotiation", "mediaOffer"):
            inner = body.get(wrapper)
            if not isinstance(inner, dict):
                continue
            cm = inner.get("callModalities")
            if isinstance(cm, list) and "ScreenSharing" not in cm:
                cm.append("ScreenSharing")
                patched = True
                logger.debug("Patched %s.callModalities: %s", wrapper, cm)

        return patched

    _CHROME_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    )

    @staticmethod
    def _patch_platform_headers(
        headers: dict,  # type: ignore[type-arg]
    ) -> list[dict[str, str]] | None:
        """Rewrite platform and browser identifiers in request headers.

        Patches ``User-Agent`` (remove HeadlessChrome / Linux),
        ``sec-ch-ua-platform``, ``sec-ch-ua``, and
        ``X-Microsoft-Skype-Client`` so the Teams server sees a
        standard Chrome on macOS client.
        """
        changed = False
        result: list[dict[str, str]] = []
        for name, val in headers.items():
            lower = name.lower()
            out = val
            if lower == "x-microsoft-skype-client" and "os=linux" in val:
                out = val.replace("os=linux", "os=macos").replace(
                    "osVer=undefined", "osVer=10.15.7"
                )
                changed = True
                logger.debug("Patched X-Microsoft-Skype-Client header")
            elif lower == "sec-ch-ua-platform" and "linux" in val.lower():
                out = '"macOS"'
                changed = True
            elif lower == "user-agent" and ("HeadlessChrome" in val or "Linux" in val):
                out = BrowserMeetingProvider._CHROME_UA
                changed = True
            elif lower == "sec-ch-ua" and (
                "HeadlessChrome" in val or "Chromium" in val
            ):
                out = (
                    '"Google Chrome";v="133", "Chromium";v="133", "Not_A Brand";v="24"'
                )
                changed = True
            result.append({"name": name, "value": out})
        return result if changed else None

    @staticmethod
    def _patch_response_fields(body: dict) -> bool:  # type: ignore[type-arg]
        """Patch server response to enable video and ScreenSharing.

        Modifies ``allowIPVideo``, ``endpointCapabilities``, and
        ``callModalities`` in the server's response so the Teams SDK
        believes video and screen sharing are permitted.

        Returns ``True`` if any field was modified.
        """
        patched = False
        patched = BrowserMeetingProvider._patch_allow_ip_video(body) or patched
        patched = BrowserMeetingProvider._patch_roster_caps(body) or patched

        # Patch nested media wrappers in responses and log SDP
        for wrapper in ("mediaAnswer", "mediaNegotiation", "mediaOffer"):
            inner = body.get(wrapper)
            if not isinstance(inner, dict):
                continue
            cm = inner.get("callModalities")
            if isinstance(cm, list) and "ScreenSharing" not in cm:
                cm.append("ScreenSharing")
                patched = True
                logger.debug("Patched response %s.callModalities: %s", wrapper, cm)
            # Log SDP BUNDLE info from blob
            blob = inner.get("blob", "")
            if blob and "BUNDLE" in str(blob):
                for line in str(blob).split("\\r\\n"):
                    if "BUNDLE" in line:
                        logger.debug("SDP %s BUNDLE: %s", wrapper, line)

        return patched

    @staticmethod
    def _patch_allow_ip_video(body: dict) -> bool:  # type: ignore[type-arg]
        """Set ``allowIPVideo`` to true in meetingCapability."""
        md = body.get("meetingDetails")
        if not isinstance(md, dict):
            return False
        mc = md.get("meetingCapability")
        if isinstance(mc, dict) and mc.get("allowIPVideo") is False:
            mc["allowIPVideo"] = True
            logger.debug("Patched allowIPVideo: false → true")
            return True
        return False

    @staticmethod
    def _patch_roster_caps(body: dict) -> bool:  # type: ignore[type-arg]
        """Add ScreenSharing bit to endpointCapabilities in roster."""
        roster = body.get("roster")
        if not isinstance(roster, dict):
            return False
        participants = roster.get("participants")
        if not isinstance(participants, dict):
            return False
        patched = False
        for pdata in participants.values():
            if not isinstance(pdata, dict):
                continue
            endpoints = pdata.get("endpoints")
            if not isinstance(endpoints, dict):
                continue
            for ep in endpoints.values():
                if not isinstance(ep, dict):
                    continue
                caps = ep.get("endpointCapabilities")
                if caps is not None and not (int(caps) & 4):
                    ep["endpointCapabilities"] = int(caps) | 4
                    patched = True
                    logger.debug(
                        "Patched server endpointCapabilities: %s → %s",
                        caps,
                        ep["endpointCapabilities"],
                    )
        return patched

    async def _install_signaling_interceptor(self, page: Page) -> None:
        """Intercept Teams signaling to inject ScreenSharing capabilities.

        The Teams calling SDK may exclude ScreenSharing from
        ``callModalities`` and ``clientEndpointCapabilities`` based on
        environment checks unrelated to ``getDisplayMedia`` availability.
        This interceptor uses CDP ``Fetch`` to modify both outgoing
        requests and incoming responses, ensuring the server allocates
        a ScreenSharing transceiver and the client honours it.
        """
        import base64
        import json

        # Reuse the CDP session created by _setup_teams_platform_spoof
        cdp = self._signaling_cdp
        if cdp is None:
            cdp = await page.context.new_cdp_session(page)
            self._signaling_cdp = cdp

        await cdp.send(
            "Fetch.enable",
            {
                "patterns": [
                    {"urlPattern": "*conv.skype.com*", "requestStage": "Request"},
                    {"urlPattern": "*flightproxy*", "requestStage": "Request"},
                    {"urlPattern": "*broker.skype.com*", "requestStage": "Request"},
                    {"urlPattern": "*conv.skype.com*", "requestStage": "Response"},
                    {"urlPattern": "*flightproxy*", "requestStage": "Response"},
                    {"urlPattern": "*broker.skype.com*", "requestStage": "Response"},
                ],
            },
        )

        async def _on_request_paused(params: dict) -> None:  # type: ignore[type-arg]
            request_id = params["requestId"]

            # Response stage: patch server responses
            if params.get("responseStatusCode") is not None:
                await self._handle_response_intercept(cdp, params, request_id)
                return

            # Request stage: patch headers and body
            request = params.get("request", {})
            headers = request.get("headers", {})
            patched_headers = self._patch_platform_headers(headers)
            post_data = request.get("postData", "")

            if request.get("method") != "POST" or not post_data:
                cont: dict = {"requestId": request_id}
                if patched_headers is not None:
                    cont["headers"] = patched_headers
                await cdp.send("Fetch.continueRequest", cont)
                return

            body_encoded = None
            try:
                body = json.loads(post_data)
                if self._patch_screensharing_fields(body):
                    body_encoded = base64.b64encode(json.dumps(body).encode()).decode()
            except (json.JSONDecodeError, ValueError, TypeError):
                logger.debug("Signaling body not JSON, passing through")

            cont = {"requestId": request_id}
            if patched_headers is not None:
                cont["headers"] = patched_headers
            if body_encoded is not None:
                cont["postData"] = body_encoded
            await cdp.send("Fetch.continueRequest", cont)

        cdp.on("Fetch.requestPaused", _on_request_paused)

    async def _handle_response_intercept(
        self,
        cdp: CDPSession,
        params: dict,  # type: ignore[type-arg]
        request_id: str,
    ) -> None:
        """Patch server responses to enable ScreenSharing.

        Must ALWAYS call ``continueResponse`` or ``fulfillRequest``
        to avoid stalling the browser's network stack.
        """
        import base64
        import json

        try:
            resp = await cdp.send("Fetch.getResponseBody", {"requestId": request_id})
            body_str = resp.get("body", "")
            is_b64 = resp.get("base64Encoded", False)

            # Decode base64 responses (compressed/binary bodies)
            if is_b64 and body_str:
                try:
                    body_str = base64.b64decode(body_str).decode("utf-8")
                except (UnicodeDecodeError, ValueError):
                    # Binary body (not text) — pass through
                    await cdp.send(
                        "Fetch.continueResponse",
                        {"requestId": request_id},
                    )
                    return

            if not body_str:
                await cdp.send(
                    "Fetch.continueResponse",
                    {"requestId": request_id},
                )
                return

            body = json.loads(body_str)
            patched = self._patch_response_fields(body)
            if patched:
                new_body = json.dumps(body)
                encoded = base64.b64encode(new_body.encode()).decode()
                await cdp.send(
                    "Fetch.fulfillRequest",
                    {
                        "requestId": request_id,
                        "responseCode": params["responseStatusCode"],
                        "responseHeaders": params.get("responseHeaders", []),
                        "body": encoded,
                    },
                )
                return
        except (json.JSONDecodeError, ValueError, TypeError, KeyError):
            pass
        except Exception:  # noqa: BLE001
            # CDP errors (network, protocol) — must still release request
            logger.debug("Response intercept CDP error, passing through")

        try:
            await cdp.send(
                "Fetch.continueResponse",
                {"requestId": request_id},
            )
        except Exception:  # noqa: BLE001
            logger.debug("continueResponse failed for %s", request_id)

    async def _setup_tab_capture_override(self, page: Page) -> None:
        """Override getDisplayMedia on the meeting page to use tab self-capture.

        Chromium's X11 screen capturer fails on aarch64 Docker/Xvfb, but
        tab self-capture (``displaySurface: "browser"``) works because it
        bypasses the X11 path entirely.  This override forces every
        ``getDisplayMedia`` call on the page to request tab capture.
        """
        await page.evaluate(
            """() => {
            if (window.__joinlyGDMOverrideInstalled) return;
            const md = navigator.mediaDevices;
            const origGDM = md.getDisplayMedia.bind(md);
            md.getDisplayMedia = async (constraints) => {
                constraints = constraints || {};
                constraints.selfBrowserSurface = 'include';
                if (!constraints.video || constraints.video === true) {
                    constraints.video = {displaySurface: 'browser'};
                } else if (typeof constraints.video === 'object') {
                    constraints.video.displaySurface = 'browser';
                }
                return origGDM(constraints);
            };
            window.__joinlyGDMOverrideInstalled = true;
            }"""
        )

    async def _setup_teams_tab_capture(self, page: Page) -> None:
        """Override getDisplayMedia at share time for tab self-capture.

        The init-script intentionally leaves ``getDisplayMedia`` native
        so the Teams SDK includes ScreenSharing in its capability
        negotiation.  This method installs the override only when
        sharing actually starts.

        A short delay is added before resolving to allow Teams'
        signaling to allocate the sharing transceiver on the server.

        If tab self-capture fails (e.g. on aarch64 Docker), falls
        back to a canvas ``captureStream``.  The video track's
        ``getSettings`` is patched so ``displaySurface`` reports
        ``'monitor'``, matching what Teams expects for screen shares.
        """
        await page.evaluate(
            """() => {
            const _sym = Symbol.for('__joinly__');
            const store = navigator.mediaDevices[_sym];
            if (!store || store.overrideInstalled) return;
            const md = navigator.mediaDevices;
            const origGDM = store.origGDM
                || MediaDevices.prototype.getDisplayMedia;

            /* Install getDisplayMedia override now (share time) */
            const newGDM = function getDisplayMedia(constraints) {
                const h = md[_sym]?.gdmHandler;
                if (h) return h(constraints, origGDM.bind(this));
                return origGDM.call(this, constraints);
            };
            /* Stealth: masquerade the late-installed override */
            const ns = store.nativeStrings;
            if (ns) {
                Object.defineProperty(newGDM, 'name',
                    {value: 'getDisplayMedia', configurable: true});
                Object.defineProperty(newGDM, 'length',
                    {value: 1, configurable: true});
                ns.set(newGDM,
                    'function getDisplayMedia() { [native code] }');
            }
            MediaDevices.prototype.getDisplayMedia = newGDM;

            store.gdmHandler = async (cstr, nativeGDM) => {
                await new Promise(r => setTimeout(r, 2000));
                let stream;
                try {
                    const tc = Object.assign({}, cstr || {});
                    tc.selfBrowserSurface = 'include';
                    tc.video = {displaySurface: 'browser'};
                    stream = await nativeGDM(tc);
                } catch (_) {
                    /* Tab capture failed — canvas fallback */
                    const cvs = document.createElement('canvas');
                    cvs.width = 1280; cvs.height = 720;
                    const ctx = cvs.getContext('2d');
                    ctx.fillStyle = '#1a1a2e';
                    ctx.fillRect(0, 0, 1280, 720);
                    stream = cvs.captureStream(15);
                }
                /* Patch displaySurface so Teams treats it as screen */
                for (const t of stream.getVideoTracks()) {
                    const orig = t.getSettings.bind(t);
                    t.getSettings = () => {
                        const s = orig();
                        s.displaySurface = 'monitor';
                        return s;
                    };
                }
                return stream;
            };
            store.overrideInstalled = true;
            }"""
        )

    async def _setup_content_overlay(
        self, meeting_page: Page, content_page: Page
    ) -> None:
        """Overlay content_page frames on meeting_page for tab capture.

        Injects a full-screen canvas on *meeting_page* that receives
        CDP screencast frames from *content_page*.  Combined with the
        tab self-capture ``getDisplayMedia`` override, meeting
        participants see the content page instead of the meeting UI.
        """
        cdp = await content_page.context.new_cdp_session(content_page)
        await cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 80,
                "maxWidth": 1280,
                "maxHeight": 720,
                "everyNthFrame": 1,
            },
        )

        await meeting_page.evaluate(
            """() => {
            if (window.__joinlyGDMOverrideInstalled) return;
            const c = document.createElement('canvas');
            c.id = '__joinlyOverlay';
            c.width = 1280; c.height = 720;
            c.style.position = 'fixed';
            c.style.inset = '0';
            c.style.width = '100vw';
            c.style.height = '100vh';
            c.style.zIndex = '999999';
            c.style.pointerEvents = 'none';
            const ctx = c.getContext('2d');
            ctx.fillStyle = '#1a1a2e';
            ctx.fillRect(0, 0, 1280, 720);
            ctx.fillStyle = '#fff';
            ctx.font = '28px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Loading…', 640, 360);
            document.body.appendChild(c);
            window.__pushFrame = (b64) => {
                const img = new Image();
                img.onload = () => {
                    ctx.drawImage(img, 0, 0, 1280, 720);
                };
                img.src = 'data:image/jpeg;base64,' + b64;
            };
            const md = navigator.mediaDevices;
            const origGDM = md.getDisplayMedia.bind(md);
            md.getDisplayMedia = async (constraints) => {
                constraints = constraints || {};
                constraints.selfBrowserSurface = 'include';
                if (!constraints.video
                    || constraints.video === true) {
                    constraints.video = {
                        displaySurface: 'browser'
                    };
                } else if (
                    typeof constraints.video === 'object') {
                    constraints.video.displaySurface =
                        'browser';
                }
                return origGDM(constraints);
            };
            window.__joinlyGDMOverrideInstalled = true;
            }"""
        )

        async def _on_frame(params: dict) -> None:  # type: ignore[type-arg]
            data = params.get("data", "")
            if data:
                await meeting_page.evaluate(
                    "(b64) => window.__pushFrame?.(b64)",
                    data,
                )
            await cdp.send(
                "Page.screencastFrameAck",
                {"sessionId": params.get("sessionId", 0)},
            )

        cdp.on("Page.screencastFrame", _on_frame)

    async def _setup_teams_content_overlay(
        self, meeting_page: Page, content_page: Page
    ) -> None:
        """Overlay content via canvas captureStream for Teams screen sharing.

        Captures *content_page* frames via CDP screencast, draws them
        on a canvas overlay, then returns ``canvas.captureStream()``
        from the ``getDisplayMedia`` handler.  The ``getDisplayMedia``
        override is installed here at share time (not during init) so
        the Teams SDK sees the native function when negotiating
        capabilities.
        """
        cdp = await content_page.context.new_cdp_session(content_page)
        await cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 80,
                "maxWidth": 1280,
                "maxHeight": 720,
                "everyNthFrame": 1,
            },
        )

        # Inject canvas overlay, install getDisplayMedia override,
        # and set the GDM handler.
        await meeting_page.evaluate(
            """() => {
            const _sym = Symbol.for('__joinly__');
            const store = navigator.mediaDevices[_sym];
            if (!store || store.overrideInstalled) return;
            const md = navigator.mediaDevices;
            const origGDM = store.origGDM
                || MediaDevices.prototype.getDisplayMedia;

            const c = document.createElement('canvas');
            c.id = '__joinlyOverlay';
            c.width = 1280; c.height = 720;
            c.style.cssText = [
                'position:fixed', 'inset:0',
                'width:100vw', 'height:100vh',
                'z-index:999999', 'pointer-events:none',
            ].join(';');
            const ctx = c.getContext('2d');
            ctx.fillStyle = '#1a1a2e';
            ctx.fillRect(0, 0, 1280, 720);
            ctx.fillStyle = '#fff';
            ctx.font = '28px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Loading\\u2026', 640, 360);
            document.body.appendChild(c);

            window.__pushFrame = (b64) => {
                const img = new Image();
                img.onload = () => {
                    ctx.drawImage(img, 0, 0, 1280, 720);
                };
                img.src = 'data:image/jpeg;base64,' + b64;
            };

            /* Continuously repaint the canvas so captureStream
               always has fresh frames to encode. */
            let _lastImg = null;
            const _repaint = () => {
                if (_lastImg) ctx.drawImage(_lastImg, 0, 0, 1280, 720);
            };
            window.__canvasRepaintId = setInterval(_repaint, 66);
            window.__pushFrame = (b64) => {
                const img = new Image();
                img.onload = () => {
                    _lastImg = img;
                    ctx.drawImage(img, 0, 0, 1280, 720);
                };
                img.src = 'data:image/jpeg;base64,' + b64;
            };

            /* Install getDisplayMedia override now (share time) */
            const newGDM = function getDisplayMedia(constraints) {
                const h = md[_sym]?.gdmHandler;
                if (h) return h(constraints, origGDM.bind(this));
                return origGDM.call(this, constraints);
            };
            const ns = store.nativeStrings;
            if (ns) {
                Object.defineProperty(newGDM, 'name',
                    {value: 'getDisplayMedia', configurable: true});
                Object.defineProperty(newGDM, 'length',
                    {value: 1, configurable: true});
                ns.set(newGDM,
                    'function getDisplayMedia() { [native code] }');
            }
            MediaDevices.prototype.getDisplayMedia = newGDM;

            /* Handler: use tab self-capture so Teams gets a real
               browser-produced stream.  The overlay canvas makes
               the content visible in the captured tab.
               Falls back to the overlay canvas captureStream. */
            store.gdmHandler = async (cstr, nativeGDM) => {
                await new Promise(r => setTimeout(r, 2000));
                let stream;
                try {
                    const tc = Object.assign({}, cstr || {});
                    tc.selfBrowserSurface = 'include';
                    tc.preferCurrentTab = true;
                    tc.video = {displaySurface: 'browser'};
                    stream = await nativeGDM(tc);
                } catch (_) {
                    /* Tab capture failed — use overlay canvas */
                    stream = c.captureStream(15);
                }
                for (const t of stream.getVideoTracks()) {
                    const orig = t.getSettings.bind(t);
                    t.getSettings = () => {
                        const s = orig();
                        s.displaySurface = 'monitor';
                        return s;
                    };
                }
                return stream;
            };

            store.overrideInstalled = true;
            }"""
        )

        async def _on_frame(params: dict) -> None:  # type: ignore[type-arg]
            data = params.get("data", "")
            if data:
                await meeting_page.evaluate(
                    "(b64) => window.__pushFrame?.(b64)",
                    data,
                )
            await cdp.send(
                "Page.screencastFrameAck",
                {"sessionId": params.get("sessionId", 0)},
            )

        cdp.on("Page.screencastFrame", _on_frame)

    async def share_screen(self, url: str | None = None) -> None:
        """Start sharing screen in the meeting.

        When *url* is provided, a full-screen canvas overlay is injected
        on the meeting tab showing CDP screencast frames from the content
        tab.  Tab self-capture then captures the overlay so meeting
        participants see the content.  Without a URL, plain tab
        self-capture is used.

        Args:
            url: Optional URL to display while sharing.
        """
        if self._is_sharing:
            msg = (
                "Already sharing screen. "
                "Stop the current share before starting a new one."
            )
            raise RuntimeError(msg)

        content_page = None
        if url:
            content_page = await self._browser_session.get_page()
            await content_page.goto(url, wait_until="load", timeout=20000)

        try:
            async with self._action_guard("share_screen") as (page, controller):
                is_teams = isinstance(controller, TeamsBrowserPlatformController)
                if content_page:
                    if is_teams:
                        await self._setup_teams_content_overlay(page, content_page)
                    else:
                        await self._setup_content_overlay(page, content_page)
                elif is_teams:
                    await self._setup_teams_tab_capture(page)
                else:
                    await self._setup_tab_capture_override(page)
                await controller.share_screen(page)
                self._content_page = content_page
                content_page = None  # ownership transferred
                self._is_sharing = True
        finally:
            if content_page and not content_page.is_closed():
                await content_page.close()

    async def _remove_share_overlay(self, page: Page) -> None:
        """Remove the full-screen share overlay from the meeting page."""
        await page.evaluate(
            """() => {
            const el = document.getElementById('__joinlyOverlay');
            if (el) el.remove();
            window.__pushFrame = null;
            const _sym = Symbol.for('__joinly__');
            const store = navigator.mediaDevices[_sym];
            if (store) {
                store.gdmHandler = null;
                store.overrideInstalled = false;
            }
            if (window.__canvasRepaintId) {
                clearInterval(window.__canvasRepaintId);
                window.__canvasRepaintId = null;
            }
            if (window.__audioCtx) {
                window.__audioCtx.close();
                window.__audioCtx = null;
            }
            }"""
        )

    async def stop_sharing(self) -> None:
        """Stop sharing screen in the meeting."""
        async with self._action_guard("stop_sharing") as (page, controller):
            try:
                await page.bring_to_front()
                await self._remove_share_overlay(page)
                await controller.stop_sharing(page)
            finally:
                await self._cleanup_content_page()

    async def snapshot(self) -> VideoSnapshot:
        """Take a snapshot of the current video frame.

        Returns:
            VideoSnapshot: The snapshot of the current video frame.
        """
        if not self._page or self._page.is_closed():
            msg = "Cannot take snapshot. Not currently in a meeting."
            logger.error(msg)
            raise RuntimeError(msg)

        raw = await self._page.screenshot(type="png")
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img = ImageOps.crop(img, border=int(min(*img.size) * 0.1))
        img = ImageOps.fit(
            img,
            self.snapshot_size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

        buf = io.BytesIO()
        img.save(buf, format="jpeg", quality=90, optimize=True, progressive=True)

        return VideoSnapshot(data=buf.getvalue(), media_type="image/jpeg")
