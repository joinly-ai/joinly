import re
from typing import ClassVar

from playwright.async_api import Page

from joinly.providers.browser.platforms.base import BaseBrowserPlatformController


class GoogleMeetBrowserPlatformController(BaseBrowserPlatformController):
    """Controller for managing Google Meet browser meetings."""

    url_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:https?://)?(?:www\.)?meet\.google\.com/"
    )

    async def join(
        self,
        page: Page,
        url: str,
        name: str,
        passcode: str | None = None,  # noqa: ARG002
    ) -> None:
        """Join the Google Meet meeting.

        Args:
            page: The Playwright page instance.
            url: The URL of the Google Meet meeting.
            name: The name of the participant.
            passcode: The passcode for the meeting (if required).
        """
        await page.goto(url, wait_until="load", timeout=20000)

        # Wait for and fill in the name field
        name_field = page.locator("#input-for-name, input[placeholder*='Your name']")
        await name_field.fill(name)

        # Click the "Join" button
        await page.click("button:has-text('Ask to join')")
