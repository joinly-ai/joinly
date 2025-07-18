import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from typing import Any, Self

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from mcp import ResourceUpdatedNotification, ServerNotification
from pydantic import AnyUrl

from joinly_client.types import SpeakerRole, Transcript, TranscriptSegment

logger = logging.getLogger(__name__)

TRANSCRIPT_URL = AnyUrl("transcript://live")
SEGMENTS_URL = AnyUrl("transcript://live/segments")


class JoinlyClient:
    """Client for interacting with the joinly server."""

    def __init__(
        self,
        url: str | FastMCP,
        *,
        name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the JoinlyClient with the server URL.

        Args:
            url (str | FastMCP): The URL of the Joinly server or a
                FastMCP instance.
            name (str | None): The name of the participant, defaults to "joinly".
            settings (dict[str, Any]): Additional settings for the client.
        """
        self.url = url
        self.settings = settings or {}
        self.name: str = name or self.settings.get("name", "joinly")
        self.settings["name"] = self.name

        self._client: Client | None = None
        self._stack = AsyncExitStack()
        self._utterance_callback: (
            Callable[[list[TranscriptSegment]], Awaitable[None]] | None
        ) = None
        self._last_utterance: float = 0.0
        self._segment_callback: (
            Callable[[list[TranscriptSegment]], Awaitable[None]] | None
        ) = None
        self._last_segment: float = 0.0
        self._tasks: set[asyncio.Task] = set()

    @property
    def client(self) -> Client:
        """Get the current client instance.

        Returns:
            Client: The current client instance.

        Raises:
            RuntimeError: If the client is not connected.
        """
        if self._client is None:
            msg = "Client is not connected"
            raise RuntimeError(msg)
        return self._client

    def set_utterance_callback(
        self, callback: Callable[[list[TranscriptSegment]], Awaitable[None]]
    ) -> None:
        """Set a callback to be called on utterance events.

        Args:
            callback (Callable[[list[TranscriptSegment]], Awaitable[None]]):
                The callback to be called with new transcript segments.
        """
        self._utterance_callback = callback
        if self._client is not None:
            self._track_task(
                asyncio.create_task(
                    self._client.session.subscribe_resource(TRANSCRIPT_URL)
                )
            )

    def unset_utterance_callback(self) -> None:
        """Unset the utterance callback."""
        self._utterance_callback = None
        if self._client is not None:
            self._track_task(
                asyncio.create_task(
                    self._client.session.unsubscribe_resource(TRANSCRIPT_URL)
                )
            )

    def set_segment_callback(
        self, callback: Callable[[list[TranscriptSegment]], Awaitable[None]]
    ) -> None:
        """Set a callback to be called on segment events.

        Args:
            callback (Callable[[list[TranscriptSegment]], Awaitable[None]]):
                The callback to be called with new transcript segments.
        """
        self._segment_callback = callback
        if self._client is not None:
            self._track_task(
                asyncio.create_task(
                    self._client.session.subscribe_resource(SEGMENTS_URL)
                )
            )

    def unset_segment_callback(self) -> None:
        """Unset the segment callback."""
        self._segment_callback = None
        if self._client is not None:
            self._track_task(
                asyncio.create_task(
                    self._client.session.unsubscribe_resource(SEGMENTS_URL)
                )
            )

    async def join_meeting(
        self,
        meeting_url: str | None,
        passcode: str | None = None,
        participant_name: str | None = None,
    ) -> None:
        """Join a meeting on the joinly server.

        Args:
            meeting_url (str | None): The URL of the meeting to join.
            passcode (str | None): The passcode for the meeting, if required.
            participant_name (str | None): The name of the participant.
        """
        if participant_name is not None:
            self.name = participant_name
        await self.client.call_tool(
            "join_meeting",
            arguments={
                "meeting_url": meeting_url,
                "passcode": passcode,
                "participant_name": self.name,
            },
        )
        self._last_utterance = 0.0
        self._last_segment = 0.0

    async def __aenter__(self) -> Self:
        """Connect to the joinly server."""
        await self._connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Disconnect from the joinly server."""
        for task in list(self._tasks):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._stack.aclose()
        self._client = None

    async def _connect(self) -> None:  # noqa: C901
        """Connect to the joinly server."""
        if self._client is not None:
            msg = "Already connected to the joinly server"
            raise RuntimeError(msg)

        async def _message_handler(message) -> None:  # noqa: ANN001
            if isinstance(message, ServerNotification) and isinstance(
                message.root, ResourceUpdatedNotification
            ):
                if message.root.params.uri == TRANSCRIPT_URL:
                    self._track_task(asyncio.create_task(self._utterance_update()))
                elif message.root.params.uri == SEGMENTS_URL:
                    self._track_task(asyncio.create_task(self._segment_update()))

        if isinstance(self.url, str):
            transport = StreamableHttpTransport(
                url=self.url,
                headers={"joinly-settings": json.dumps(self.settings)},
            )
            logger.info("Connecting to joinly server at %s", self.url)
        else:
            transport = self.url

        self._client = Client(transport=transport, message_handler=_message_handler)
        try:
            await self._stack.enter_async_context(self._client)
        except Exception:
            logger.exception("Failed to connect to joinly server")
            await self._stack.aclose()
            raise
        else:
            logger.info("Connected to joinly server")

        if self._utterance_callback:
            await self._client.session.subscribe_resource(TRANSCRIPT_URL)
        if self._segment_callback:
            await self._client.session.subscribe_resource(SEGMENTS_URL)

    def _track_task(self, task: asyncio.Task) -> None:
        """Track a task to ensure it is cleaned up on exit.

        Args:
            task (asyncio.Task): The task to track.
        """
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(
            lambda t: t.exception()
            and logger.error("Task %s failed with exception: %s", t, t.exception())
        )

    async def _utterance_update(self) -> None:
        """Update the utterance callback with new segments."""
        resource = await self.client.read_resource(TRANSCRIPT_URL)
        transcript = Transcript.model_validate_json(resource[0].text)  # type: ignore[attr-defined]
        new_transcript = transcript.with_role(SpeakerRole.participant).after(
            self._last_utterance
        )
        if new_transcript.segments:
            self._last_utterance = new_transcript.segments[-1].start
            if self._utterance_callback:
                await self._utterance_callback(new_transcript.compact().segments)

    async def _segment_update(self) -> None:
        """Update the segment callback with new segments."""
        resource = await self.client.read_resource(SEGMENTS_URL)
        transcript = Transcript.model_validate_json(resource[0].text)  # type: ignore[attr-defined]
        new_transcript = transcript.after(self._last_segment)
        if new_transcript.segments:
            self._last_segment = new_transcript.segments[-1].start
            if self._segment_callback:
                await self._segment_callback(new_transcript.segments)

    async def get_transcript(self) -> Transcript:
        """Get the full transcript from the server.

        Returns:
            Transcript: The current transcript.
        """
        result = await self.client.call_tool("get_transcript")
        return Transcript.model_validate(result.content[0].text)  # type: ignore[attr-defined]
