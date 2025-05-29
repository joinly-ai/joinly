from joinly.core import MeetingController
from joinly.types import ProviderNotSupportedError


class DefaultMeetingController(MeetingController):
    """Base class for meeting controllers."""

    async def join(self, url: str | None = None, name: str | None = None) -> None:  # noqa: ARG002
        """Join a meeting at the specified URL."""
        msg = "Provider does not support joining meetings"
        raise ProviderNotSupportedError(msg)

    async def leave(self) -> None:
        """Leave the current meeting."""
        msg = "Provider does not support leaving meetings"
        raise ProviderNotSupportedError(msg)

    async def send_chat_message(self, message: str) -> None:  # noqa: ARG002
        """Send a chat message in the meeting."""
        msg = "Provider does not support sending chat messages"
        raise ProviderNotSupportedError(msg)
