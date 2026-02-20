# ruff: noqa: T201, S101, D103, S108, E501, C901, PLR0912, PLR0915, SLF001, BLE001, S110, SIM105, TRY400, PLR2004, RUF006, ANN001, ANN202, G201
"""End-to-end test for Teams screen sharing with production code.

Uses the actual production code path (BrowserMeetingProvider) to join
a Teams meeting and attempt screen sharing.

Usage:
    uv run python scripts/test_screen_share.py <teams-meeting-url>

The bot will join the meeting and wait to be admitted.  Once admitted,
it will click the Share button.  Monitor the console output for:
  - getDisplayMedia called       (GDM interceptor working)
  - Tab capture / canvas fallback (capture method)
  - Screen sharing state changes
"""

import asyncio
import logging
import re
import sys

from joinly.providers.browser.meeting_provider import BrowserMeetingProvider
from joinly.settings import Settings, set_settings
from joinly.utils.logging import configure_logging

logger = logging.getLogger("joinly.diag")


async def main(meeting_url: str) -> None:
    configure_logging(verbose=2, quiet=False, plain=True)
    set_settings(Settings(name="joinly", vad="webrtc", stt="whisper", tts="kokoro"))

    provider = BrowserMeetingProvider()

    async with provider:
        logger.info("Joining: %s", meeting_url)
        await provider.join(url=meeting_url, name="joinly")
        logger.info("Join completed (in lobby or meeting)")

        if not provider._page:
            logger.error("No page available after join")
            return

        # Add console monitoring
        def on_console(msg):
            text = msg.text[:300]
            if any(
                kw in text.lower()
                for kw in [
                    "screensharing",
                    "displaymedia",
                    "gdm",
                    "allowipvideo",
                    "screen",
                    "share",
                    "modali",
                    "transceiver",
                    "joinly",
                ]
            ):
                logger.info("CONSOLE [%s]: %s", msg.type, text[:200])

        provider._page.on("console", on_console)

        # Wait for admission — poll every 3 seconds for up to 120 seconds
        logger.info("Waiting to be admitted (up to 120s)...")
        in_meeting = False
        for i in range(40):
            await asyncio.sleep(3)
            leave_btn = provider._page.get_by_role(
                "button", name=re.compile(r"leave", re.IGNORECASE)
            )
            try:
                if await leave_btn.is_visible():
                    in_meeting = True
                    logger.info("Admitted to meeting at t+%ds", (i + 1) * 3)
                    break
            except Exception:
                pass

            # Periodic status
            if i % 5 == 4:
                heading = await provider._page.evaluate(
                    "document.querySelector('h1,h2,h3,h4')?.textContent?.trim()?.substring(0,80) || ''"
                )
                logger.info("t+%ds: heading=%r", (i + 1) * 3, heading)

        if not in_meeting:
            logger.warning("Not admitted after 120s — taking screenshot and exiting")
            await provider._page.screenshot(path="/tmp/share_test_lobby.png")
            body = await provider._page.evaluate(
                "document.body?.innerText?.substring(0, 300) || ''"
            )
            logger.info("Page: %s", body[:200])
            return

        await provider._page.screenshot(path="/tmp/share_test_before.png")
        logger.info("In meeting — checking Share button availability...")

        # Check if share button is visible
        share_btn_visible = await provider._page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button'));
            return btns.filter(b => /share/i.test(b.textContent) || /share/i.test(b.getAttribute('aria-label') || ''))
                .map(b => ({
                    text: b.textContent?.trim()?.substring(0, 40),
                    ariaLabel: b.getAttribute('aria-label')?.substring(0, 40),
                    disabled: b.disabled,
                    visible: b.offsetParent !== null,
                }));
        }""")
        logger.info("Share buttons: %s", share_btn_visible)

        # Attempt screen share
        logger.info("Attempting screen share...")
        try:
            await provider.share_screen()
            logger.info("share_screen() returned successfully!")
            await asyncio.sleep(5)
            await provider._page.screenshot(path="/tmp/share_test_after.png")

            # Check if sharing
            logger.info("Is sharing: %s", provider._is_sharing)

            # Wait and observe
            logger.info("Waiting 15s to observe sharing state...")
            await asyncio.sleep(15)
            await provider._page.screenshot(path="/tmp/share_test_final.png")

            # Stop sharing
            logger.info("Stopping share...")
            await provider.stop_sharing()
            logger.info("Share stopped.")

        except Exception as e:
            logger.error("share_screen() failed: %s", e, exc_info=True)
            await provider._page.screenshot(path="/tmp/share_test_error.png")

            # Capture page state for debugging
            body = await provider._page.evaluate(
                "document.body?.innerText?.substring(0, 500) || ''"
            )
            logger.info("Page after error: %s", body[:300])

        logger.info("Leaving...")
        try:
            await provider.leave()
        except Exception as e:
            logger.error("Leave failed: %s", e)

    logger.info("Done.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <teams-meeting-url>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
