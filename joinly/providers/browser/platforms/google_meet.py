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
        await page.locator(
            "button:has-text('Join now'), button:has-text('Ask to join')"
        ).click()

    async def leave(self, page: Page) -> None:
        """Leave the Google Meet meeting.

        Args:
            page: The Playwright page instance.
        """
        leave_btn = page.get_by_role(
            "button", name=re.compile(r"^leave", re.IGNORECASE)
        )
        await leave_btn.click(timeout=1000)
        await page.wait_for_timeout(500)

    async def mute(self, page: Page) -> None:
        """Mute the participant in the Google Meet meeting.

        Args:
            page: The Playwright page instance.
        """
        mute_btn = page.get_by_role(
            "button", name=re.compile(r"^turn off mic", re.IGNORECASE)
        )
        if await mute_btn.is_visible(timeout=2000):
            await mute_btn.click(timeout=2000)

    async def unmute(self, page: Page) -> None:
        """Unmute the participant in the Google Meet meeting.

        Args:
            page: The Playwright page instance.
        """
        unmute_btn = page.get_by_role(
            "button", name=re.compile(r"^turn on mic", re.IGNORECASE)
        )
        if await unmute_btn.is_visible(timeout=2000):
            await unmute_btn.click(timeout=2000)

    async def send_chat_message(self, page: Page, message: str) -> None:
        """Send a chat message in the Google Meet meeting.

        Args:
            page: The Playwright page instance.
            message: The message to send.
        """
        chat_input = page.locator("textarea[placeholder*='Send a message']")
        is_chat_visible = await chat_input.is_visible(timeout=1000)

        if not is_chat_visible:
            chat_button = page.get_by_role(
                "button", name=re.compile(r"^chat", re.IGNORECASE)
            )
            await chat_button.wait_for(timeout=2000)
            await chat_button.click()
            await page.wait_for_timeout(1000)

        await chat_input.wait_for(timeout=2000)
        await chat_input.fill(message)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
