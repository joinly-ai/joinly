import logging
import re
from typing import ClassVar

from playwright.async_api import Page

from joinly.providers.browser.platforms.base import BaseBrowserPlatformController

logger = logging.getLogger(__name__)


class ZoomBrowserPlatformController(BaseBrowserPlatformController):
    """Controller for managing Zoom browser meetings."""

    url_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:https?://)?(?:[a-z0-9-]+\.)?zoom\.us/"
    )

    async def join(self, page: Page, url: str, name: str) -> None:  # noqa: ARG002
        """Join the Zoom meeting.

        Args:
            page: The Playwright page instance.
            url: The URL of the Zoom meeting.
            name: The name of the participant.
        """
        if re.search(r"/j/\d+", url):
            url = re.sub(r"/j/(\d+)", r"/wc/join/\1", url)
            logger.info(f"Rewrote Zoom join URL to web client format: {url}")  # noqa: G004

        await page.goto(url, wait_until="load", timeout=20000)

        await page.click("button:has-text('ACCEPT COOKIES')", timeout=5000)
        await page.click("button:has-text('I Agree')", timeout=5000)

        # Wait for and fill name field
        name_field = page.locator("#input-for-name, input[placeholder*='Name']")
        await name_field.fill("Dan", timeout=10000)

        await page.click("button:has-text('Join')", timeout=5000)

        # If the Join button is still present, click it again
        try:
            join_button = page.locator("button:has-text('Join')")
            if await join_button.is_visible(timeout=2000):
                logger.info("Join button still present, clicking again.")
                await join_button.click(timeout=5000)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"No additional Join button found or error occurred: {e}")  # noqa: G004

    async def leave(self, page: Page) -> None:
        """Leave the Zoom meeting using icon-based button."""
        # Click at the center
        await page.mouse.click(640, 360)

        # Step 1: Hover to trigger visibility of the Leave button
        await page.hover("footer, div[class*='footer']")

        # Step 2: Click the Leave button using the span content
        await page.click(
            "button:has(span.footer-button-base__button-label:has-text('Leave'))"
        )

        try:
            leave_button = page.locator(
                "button:has(span.footer-button-base__button-label:has-text('Leave'))"
            )
            if await leave_button.is_visible(timeout=2000):
                logger.info("Join button still present, clicking again.")
                await leave_button.click(timeout=5000)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"No additional Join button found or error occurred: {e}")  # noqa: G004

        await page.click(
            "button.leave-meeting-options__btn--danger:has-text('Leave meeting')",
            timeout=5000,
        )

    async def send_chat_message(self, page: Page, message: str) -> None:
        """Send a chat message in Zoom."""
        chat_input = page.locator("div[contenteditable='true']")
        is_chat_visible = await chat_input.is_visible(timeout=1000)

        if not is_chat_visible:
            # Click at the center
            await page.mouse.click(640, 360)

            # Step 1: Hover to trigger visibility of the Leave button
            await page.hover("footer, div[class*='footer']")

            await page.wait_for_selector(
                "button[aria-label='open the chat panel']", timeout=2000
            )

            # Step 2: Click the button
            await page.click("button[aria-label='open the chat panel']")
            await page.click("button[aria-label='open the chat panel']")

        # Fokus setzen (wichtig für ProseMirror)
        await chat_input.click()
        await page.wait_for_timeout(200)

        # Nachricht tippen (nutzt JS DOM API für maximale Kompatibilität)
        await chat_input.fill(message)
        await page.wait_for_timeout(200)

        # Nachricht abschicken
        await page.keyboard.press("Enter")

    async def start_screen_sharing(self, page: Page) -> None:
        """Start screen sharing in Zoom."""
        share_btn = page.get_by_role(
            "button", name=re.compile(r"Share Screen", re.IGNORECASE)
        )
        await share_btn.click(timeout=2000)
        await page.wait_for_timeout(500)

        screen_option = page.get_by_role(
            "button", name=re.compile(r"Screen 1|Entire Screen", re.IGNORECASE)
        )
        await screen_option.click(timeout=2000)
        await page.wait_for_timeout(500)
