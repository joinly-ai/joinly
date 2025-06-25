import re
from typing import ClassVar, Protocol

from playwright.async_api import Page

from joinly.types import (
    MeetingChatHistory,
    MeetingParticipant,
    ProviderNotSupportedError,
)


class BrowserPlatformController(Protocol):
    """Protocol for controlling meeting interactions.

    Defines the interface for joining, interacting with, and leaving meetings
    using a browser.
    """

    url_pattern: ClassVar[re.Pattern[str]]

    @property
    def active_speaker(self) -> str | None:
        """Get the name of the active speaker in the meeting.

        Returns:
            str | None: The name of the active speaker, or None if not available.
        """
        ...

    async def join(
        self, page: Page, url: str, name: str, passcode: str | None = None
    ) -> None:
        """Join a meeting.

        Args:
            page: The Playwright Page object to interact with.
            url: The meeting URL to join.
            name: The name to use in the meeting.
            passcode: The passcode for the meeting (if required).
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

    async def get_chat_history(self, page: Page) -> MeetingChatHistory:
        """Get the chat message history from the meeting.

        Args:
            page: The Playwright Page object to interact with.

        Returns:
            MeetingChatHistory: The chat history of the meeting.
        """
        ...

    async def get_participants(self, page: Page) -> list[MeetingParticipant]:
        """Get the list of participants in the meeting.

        Args:
            page: The Playwright Page object to interact with.

        Returns:
            list[MeetingParticipant]: A list of participants in the meeting.
        """
        ...

    async def mute(self, page: Page) -> None:
        """Mute yourself in the meeting.

        Args:
            page: The Playwright Page object to interact with.
        """
        ...

    async def unmute(self, page: Page) -> None:
        """Unmute yourself in the meeting.

        Args:
            page: The Playwright Page object to interact with.
        """
        ...


class BaseBrowserPlatformController(BrowserPlatformController):
    """Base class for browser platform controllers for specific platforms."""

    url_pattern: ClassVar[re.Pattern[str]] = re.compile(r"^$")

    @property
    def active_speaker(self) -> str | None:
        """Get the name of the active speaker in the meeting."""
        return None

    async def join(
        self,
        page: Page,  # noqa: ARG002
        url: str,  # noqa: ARG002
        name: str,  # noqa: ARG002
        passcode: str | None = None,  # noqa: ARG002
    ) -> None:
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

    async def get_chat_history(self, page: Page) -> MeetingChatHistory:  # noqa: ARG002
        """Get the chat history from the meeting."""
        msg = "Provider does not support retrieving chat history."
        raise ProviderNotSupportedError(msg)

    async def get_participants(self, page: Page) -> list[MeetingParticipant]:  # noqa: ARG002
        """Get the list of participants in the meeting."""
        msg = "Provider does not support retrieving participants."
        raise ProviderNotSupportedError(msg)

    async def mute(self, page: Page) -> None:  # noqa: ARG002
        """Mute yourself in the meeting."""
        msg = "Provider does not support muting."
        raise ProviderNotSupportedError(msg)

    async def unmute(self, page: Page) -> None:  # noqa: ARG002
        """Unmute yourself in the meeting."""
        msg = "Provider does not support unmuting."
        raise ProviderNotSupportedError(msg)
