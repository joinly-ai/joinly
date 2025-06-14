import asyncio
import contextlib
import logging
import re
from typing import ClassVar

from playwright.async_api import Page

from joinly.providers.browser.platforms.base import BaseBrowserPlatformController

logger = logging.getLogger(__name__)


class TeamsBrowserPlatformController(BaseBrowserPlatformController):
    """Controller for managing Teams browser meetings."""

    url_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:https?://)?(?:[a-z0-9-]+\.)?teams\.microsoft\.com/"
    )

    async def join(
        self,
        page: Page,
        url: str,
        name: str,
        passcode: str | None = None,  # noqa: ARG002
    ) -> None:
        """Join the Teams meeting.

        Args:
            page: The Playwright page instance.
            url: The URL of the Teams meeting.
            name: The name of the participant.
            passcode: The passcode for the meeting (if required).
        """
        await page.goto(url, wait_until="load", timeout=20000)

        async def _dismiss_audio_missing(page: Page) -> None:
            await page.click("button:has-text('Continue without audio')", timeout=0)

        dismiss_audio_missing = asyncio.create_task(_dismiss_audio_missing(page))

        try:
            name_field = page.get_by_placeholder(re.compile("name", re.IGNORECASE))
            await name_field.fill(name, timeout=20000)

            join_btn = page.get_by_role(
                "button", name=re.compile(r"^join", re.IGNORECASE)
            )
            await join_btn.click(timeout=3000)

        finally:
            dismiss_audio_missing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dismiss_audio_missing

    async def leave(self, page: Page) -> None:
        """Leave the Teams meeting.

        Args:
            page: The Playwright page instance.
        """
        leave_btn = page.get_by_role(
            "button", name=re.compile(r"^leave", re.IGNORECASE)
        )
        await leave_btn.click(timeout=1000)
        await page.wait_for_timeout(500)

    async def send_chat_message(self, page: Page, message: str) -> None:
        """Send a chat message in the Teams meeting.

        Args:
            page: The Playwright page instance.
            message: The message to send.
        """
        chat_input = page.locator("div[contenteditable='true']")
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

    async def mute(self, page: Page) -> None:
        """Mute the participant in the Teams meeting.

        Args:
            page: The Playwright page instance.
        """
        mute_btn = page.get_by_role("button", name=re.compile(r"^mute", re.IGNORECASE))
        if await mute_btn.is_visible(timeout=2000):
            await mute_btn.click(timeout=2000)

    async def unmute(self, page: Page) -> None:
        """Unmute the participant in the Teams meeting.

        Args:
            page: The Playwright page instance.
        """
        unmute_btn = page.get_by_role(
            "button", name=re.compile(r"^unmute", re.IGNORECASE)
        )
        if await unmute_btn.is_visible(timeout=2000):
            await unmute_btn.click(timeout=2000)

    async def start_screen_sharing(self, page: Page) -> None:
        """Start screen sharing in the Teams meeting.

        Args:
            page: The Playwright page instance.
        """
        screen_share_btn = page.get_by_role(
            "button", name=re.compile(r"^share", re.IGNORECASE)
        )
        await screen_share_btn.wait_for(timeout=2000)
        await screen_share_btn.click(timeout=2000)
        await page.wait_for_timeout(500)

        screen_share_btn = page.get_by_role(
            "button", name=re.compile(r"^share a screen", re.IGNORECASE)
        )
        await screen_share_btn.wait_for(timeout=2000)
        await screen_share_btn.click(timeout=2000)
