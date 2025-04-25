import logging
from collections.abc import AsyncIterator
from typing import override

from meeting_agent.core.async_processor import AsyncBufferedProcessor

logger = logging.getLogger(__name__)


class MeetingAgent(AsyncBufferedProcessor[str, str]):
    """A class to represent a meeting agent."""

    def __init__(self, upstream: AsyncIterator[str]) -> None:
        """Initialize a meeting agent."""
        super().__init__(upstream, buffer_size=10)

    @override
    async def on_start(self) -> None:
        """Initialize the meeting agent."""

    @override
    async def process(self, item: str) -> AsyncIterator[str]:
        """Process the input text and yield responses.

        Args:
            item: Input text.

        Yields:
            str: Processed response.
        """
        yield item
