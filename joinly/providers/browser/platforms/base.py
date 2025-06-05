import re
from typing import ClassVar, Protocol

from playwright.async_api import Page

from joinly.types import ProviderNotSupportedError


class BrowserPlatformController(Protocol):
    """Protocol for controlling meeting interactions.

    Defines the interface for joining, interacting with, and leaving meetings
    using a browser.
    """

    url_pattern: ClassVar[re.Pattern[str]]

    async def join(self, page: Page, url: str, name: str) -> None:
        """Join a meeting.

        Args:
            page: The Playwright Page object to interact with.
            url: The meeting URL to join.
            name: The name to use in the meeting.
        """
        ...

    async def leave(self, page: Page) -> None:
        """Leave the current meeting.

        Args:
            page: The Playwright Page object to interact with.
        """
        ...

    async def send_chat_message(self, page: Page, message: str) -> None:
        """Send a chat message to the meeting.

        Args:
            page: The Playwright Page object to interact with.
            message: The message to send.
        """
        ...


class BaseBrowserPlatformController(BrowserPlatformController):
    """Base class for browser platform controllers for specific platforms."""

    url_pattern: ClassVar[re.Pattern[str]] = re.compile(r"^$")

    async def join(self, page: Page, url: str, name: str) -> None:  # noqa: ARG002
        """Join a meeting at the specified URL."""
        msg = "Provider does not support joining meetings."
        raise ProviderNotSupportedError(msg)

    async def leave(self, page: Page) -> None:  # noqa: ARG002
        """Leave the current meeting."""
        msg = "Provider does not support leaving meetings."
        raise ProviderNotSupportedError(msg)

    async def send_chat_message(self, page: Page, message: str) -> None:  # noqa: ARG002
        """Send a chat message in the meeting."""
        msg = "Provider does not support sending chat messages."
        raise ProviderNotSupportedError(msg)
