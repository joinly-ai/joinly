from joinly.core import MeetingProvider
from joinly.types import (
    MeetingChatHistory,
    MeetingParticipant,
    ProviderNotSupportedError,
)


class BaseMeetingProvider(MeetingProvider):
    """Base class for meeting providers."""

    async def join(
        self,
        url: str | None = None,  # noqa: ARG002
        name: str | None = None,  # noqa: ARG002
        passcode: str | None = None,  # noqa: ARG002
    ) -> None:
        """Join a meeting at the specified URL."""
        msg = "Provider does not support joining meetings."
        raise ProviderNotSupportedError(msg)

    async def leave(self) -> None:
        """Leave the current meeting."""
        msg = "Provider does not support leaving meetings."
        raise ProviderNotSupportedError(msg)

    async def send_chat_message(self, message: str) -> None:  # noqa: ARG002
        """Send a chat message in the meeting."""
        msg = "Provider does not support sending chat messages."
        raise ProviderNotSupportedError(msg)

    async def get_chat_history(self) -> MeetingChatHistory:
        """Get the chat message history from the meeting."""
        msg = "Provider does not support retrieving chat history."
        raise ProviderNotSupportedError(msg)

    async def get_participants(self) -> list[MeetingParticipant]:
        """Get the list of participants in the meeting."""
        msg = "Provider does not support retrieving participants."
        raise ProviderNotSupportedError(msg)

    async def mute(self) -> None:
        """Mute yourself in the meeting."""
        msg = "Provider does not support muting."
        raise ProviderNotSupportedError(msg)

    async def unmute(self) -> None:
        """Unmute yourself in the meeting."""
        msg = "Provider does not support unmuting."
        raise ProviderNotSupportedError(msg)
