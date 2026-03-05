"""Screen sharing via canvas overlay and tab self-capture.

Injects a full-screen ``<canvas>`` on the meeting tab that receives CDP
screencast frames from a separate content tab.  A ``getDisplayMedia``
override uses tab self-capture so the platform receives a real
browser-produced stream containing the canvas content.

The canvas sits at ``z-index:999999`` with ``pointer-events:none`` so
Playwright automation on the meeting page still works (clicks pass
through to the DOM underneath).
"""

from playwright.async_api import Page

_INSTALL_OVERLAY_JS = """\
({ w, h }) => {
    if (window.__scGDMInstalled) return;

    const c = document.createElement('canvas');
    c.id = '__scOverlay';
    c.width = w; c.height = h;
    c.style.cssText = [
        'position:fixed', 'inset:0',
        'width:100vw', 'height:100vh',
        'z-index:999999', 'pointer-events:none',
    ].join(';');
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, w, h);
    document.body.appendChild(c);

    let _lastImg = null;
    const _repaint = () => {
        if (_lastImg) ctx.drawImage(_lastImg, 0, 0, w, h);
    };
    window.__canvasRepaintId = setInterval(_repaint, 66);
    window.__pushFrame = (b64) => {
        const img = new Image();
        img.onload = () => {
            _lastImg = img;
            ctx.drawImage(img, 0, 0, w, h);
        };
        img.src = 'data:image/jpeg;base64,' + b64;
    };

    const md = navigator.mediaDevices;
    const origGDM = md.getDisplayMedia.bind(md);
    md.getDisplayMedia = async (constraints) => {
        constraints = constraints || {};
        constraints.audio = false;
        constraints.selfBrowserSurface = 'include';
        constraints.video = {displaySurface: 'browser'};
        try {
            const s = await origGDM(constraints);
            window.__scShareOk = true;
            return s;
        } catch (e) {
            window.__scShareOk = false;
            throw e;
        }
    };
    window.__scGDMInstalled = true;
}"""

_REMOVE_OVERLAY_JS = """\
() => {
    const el = document.getElementById('__scOverlay');
    if (el) el.remove();
    window.__pushFrame = null;
    window.__scShareOk = null;
    window.__scGDMInstalled = false;
    if (window.__canvasRepaintId) {
        clearInterval(window.__canvasRepaintId);
        window.__canvasRepaintId = null;
    }
}"""

_SCREENCAST_QUALITY = 92


async def setup_content_stream(
    meeting_page: Page,
    content_page: Page,
    size: tuple[int, int] = (1280, 720),
) -> None:
    """Start streaming *content_page* frames onto *meeting_page* via CDP.

    Installs the canvas overlay and ``getDisplayMedia`` override on the
    meeting page, then starts a CDP screencast on the content page and
    pumps each frame into the overlay canvas.

    Args:
        meeting_page: The meeting tab's Playwright page.
        content_page: The content tab whose frames will be shared.
        size: Width and height for the canvas and screencast.
    """
    width, height = size
    await meeting_page.evaluate("() => { window.__scShareOk = null; }")
    await meeting_page.evaluate(_INSTALL_OVERLAY_JS, {"w": width, "h": height})

    cdp = await content_page.context.new_cdp_session(content_page)
    await cdp.send(
        "Page.startScreencast",
        {
            "format": "jpeg",
            "quality": _SCREENCAST_QUALITY,
            "maxWidth": width,
            "maxHeight": height,
            "everyNthFrame": 1,
        },
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


async def remove_overlay(page: Page) -> None:
    """Remove the canvas overlay and reset all injected globals."""
    await page.evaluate(_REMOVE_OVERLAY_JS)
