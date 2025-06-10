import re
from typing import ClassVar

from playwright.async_api import Page

from joinly.providers.browser.platforms.base import BaseBrowserPlatformController


class MockupBrowserPlatformController(BaseBrowserPlatformController):
    """Controller for managing mockup meetings."""

    url_pattern: ClassVar[re.Pattern[str]] = re.compile(r".*")

    async def join(
        self,
        page: Page,
        url: str,
        name: str,
        passcode: str | None = None,  # noqa: ARG002
    ) -> None:
        """Join the mockup meeting.

        Args:
            page: The Playwright page instance.
            url: The URL of the mockup meeting.
            name: The name of the participant.
            passcode: The passcode for the meeting (if required).
        """
        await page.goto(url, wait_until="load", timeout=2000)
        await page.fill("#name", name, timeout=1000)
        await page.click("#join", timeout=1000)

    async def leave(self, page: Page) -> None:
        """Leave the mockup meeting.

        Args:
            page: The Playwright page instance.
        """
        await page.click("#leave", timeout=1000)
