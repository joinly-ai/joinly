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

    async def join(
        self,
        page: Page,
        url: str,
        name: str,
        passcode: str | None = None,  # noqa: ARG002
    ) -> None:
        """Join the Zoom meeting.

        Args:
            page: The Playwright page instance.
            url: The URL of the Zoom meeting.
            name: The name of the participant.
            passcode: The passcode for the meeting (if required).
        """
        # Convert the standard join URL to the web client format
        if re.search(r"/j/\d+", url):
            url = re.sub(r"/j/(\d+)", r"/wc/join/\1", url)
            logger.info(f"Rewrote Zoom join URL to web client format: {url}")  # noqa: G004

        await page.goto(url, wait_until="load", timeout=20000)

        # Accept cookies and agree to terms
        await page.click("button:has-text('ACCEPT COOKIES')", timeout=5000)
        await page.click("button:has-text('I Agree')", timeout=5000)

        # Wait for and fill in the name field
        name_field = page.locator("#input-for-name, input[placeholder*='Name']")
        await name_field.fill(name, timeout=10000)

        # Click the "Join" button
        await page.click("button:has-text('Join')", timeout=5000)

        # If the Join button is still visible, click it again
        try:
            join_button = page.locator("button:has-text('Join')")
            if await join_button.is_visible(timeout=2000):
                logger.info("Join button still present, clicking again.")
                await join_button.click(timeout=5000)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"No additional Join button found or error occurred: {e}")  # noqa: G004

    async def leave(self, page: Page) -> None:
        """Leave the Zoom meeting using the icon-based button."""
        # Click at the center of the screen to activate interface elements
        await page.mouse.click(640, 360)

        # Step 1: Hover over the footer to reveal the Leave button
        await page.hover("footer, div[class*='footer']")

        # Step 2: Click the Leave button based on its label
        await page.click(
            "button:has(span.footer-button-base__button-label:has-text('Leave'))"
        )

        # Attempt a second click if the button is still visible
        try:
            leave_button = page.locator(
                "button:has(span.footer-button-base__button-label:has-text('Leave'))"
            )
            if await leave_button.is_visible(timeout=2000):
                logger.info("Leave button still present, clicking again.")
                await leave_button.click(timeout=5000)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"No additional Leave button found or error occurred: {e}")  # noqa: G004

        # Confirm leaving the meeting
        await page.click(
            "button.leave-meeting-options__btn--danger:has-text('Leave meeting')",
            timeout=5000,
        )

    async def send_chat_message(self, page: Page, message: str) -> None:
        """Send a chat message in Zoom."""
        chat_input = page.locator("div[contenteditable='true']")
        is_chat_visible = await chat_input.is_visible(timeout=1000)

        if not is_chat_visible:
            # Click in the center to activate UI
            await page.mouse.click(640, 360)

            # Hover over the footer to show the chat button
            await page.hover("footer, div[class*='footer']")

            await page.wait_for_selector(
                "button[aria-label='open the chat panel']", timeout=2000
            )

            # Click the chat panel button twice (some UIs require this)
            await page.click("button[aria-label='open the chat panel']")
            await page.click("button[aria-label='open the chat panel']")

        # Focus the chat input (important for ProseMirror-based editors)
        await chat_input.click()
        await page.wait_for_timeout(200)

        # Type the message (using fill for DOM compatibility)
        await chat_input.fill(message)
        await page.wait_for_timeout(200)

        # Send the message
        await page.keyboard.press("Enter")

    async def start_screen_sharing(self, page: Page) -> None:
        """Start screen sharing in Zoom."""
        # Click the Share Screen button
        share_btn = page.get_by_role(
            "button", name=re.compile(r"Share Screen", re.IGNORECASE)
        )
        await share_btn.click(timeout=2000)
        await page.wait_for_timeout(500)

        # Click the option to share a specific screen (like "Screen 1" or "Entire Screen")  # noqa: E501
        screen_option = page.get_by_role(
            "button", name=re.compile(r"Screen 1|Entire Screen", re.IGNORECASE)
        )
        await screen_option.click(timeout=2000)
        await page.wait_for_timeout(500)
