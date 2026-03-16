"""Screen sharing via canvas overlay and tab self-capture.

Injects a full-screen ``<canvas>`` on the meeting tab that receives CDP
screencast frames from a separate content tab.  A ``getDisplayMedia``
override uses tab self-capture so the platform receives a real
browser-produced stream containing the canvas content.

The canvas sits at ``z-index:999999`` with ``pointer-events:none`` so
Playwright automation on the meeting page still works (clicks pass
through to the DOM underneath).
"""

from pathlib import Path

from playwright.async_api import Page

_SCREEN_SHARE_JS = (Path(__file__).parent / "static" / "screen_share.js").read_text()

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
    await meeting_page.evaluate(_SCREEN_SHARE_JS)
    await meeting_page.evaluate("window.__installOverlay", {"w": width, "h": height})

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
    await page.evaluate("window.__removeOverlay()")
