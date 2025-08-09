import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Coroutine
from contextlib import AsyncExitStack
from typing import Any, Self

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from mcp import ClientSession, McpError, ResourceUpdatedNotification, ServerNotification
from mcp.types import Tool
from pydantic import AnyUrl

from joinly_client.types import (
    MeetingChatHistory,
    MeetingParticipantList,
    SpeakerRole,
    Transcript,
    TranscriptSegment,
    Usage,
)
from joinly_client.utils import is_async_context, name_in_transcript

logger = logging.getLogger(__name__)

TRANSCRIPT_URL = AnyUrl("transcript://live")
SEGMENTS_URL = AnyUrl("transcript://live/segments")
USAGE_URL = AnyUrl("usage://current")


class JoinlyClient:
    """Client for interacting with the joinly server."""

    def __init__(
        self,
        url: str | FastMCP,
        *,
        name: str | None = None,
        name_trigger: bool = False,
        settings: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the JoinlyClient with the server URL.

        Args:
            url (str | FastMCP): The URL of the Joinly server or a
                FastMCP instance.
            name (str | None): The name of the participant, defaults to "joinly".
            name_trigger (bool): Whether to only trigger utterances when the name is
                mentioned.
            settings (dict[str, Any]): Additional settings for the client.
        """
        self.url = url
        self.settings = settings or {}
        self.name: str = name or self.settings.get("name", "joinly")
        self.name_trigger = name_trigger
        self.settings["name"] = self.name

        self.joined: bool = False
        self._client: Client | None = None
        self._stack = AsyncExitStack()
        self._utterance_callbacks: set[
            Callable[[list[TranscriptSegment]], Coroutine[None, None, None]]
        ] = set()
        self._last_utterance: float = 0.0
        self._segment_callbacks: set[
            Callable[[list[TranscriptSegment]], Coroutine[None, None, None]]
        ] = set()
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

    @property
    def session(self) -> ClientSession:
        """Get the current session instance.

        Returns:
            Session: The current session instance.

        Raises:
            RuntimeError: If the client is not connected.
        """
        return self.client.session

    def add_utterance_callback(
        self, callback: Callable[[list[TranscriptSegment]], Coroutine[None, None, None]]
    ) -> Callable[[], None]:
        """Add a callback to be called on utterance events.

        Args:
            callback (Callable[[list[TranscriptSegment]], Coroutine[None, None, None]]):
                The callback to be called with new transcript segments.

        Returns:
            Callable[[], None]: A function to remove the callback.
        """
        if (
            self._client is not None
            and not self._utterance_callbacks
            and is_async_context()
        ):
            # update last utterance and subscribe
            async def _subscribe() -> None:
                await self._utterance_update()
                self._utterance_callbacks.add(callback)
                await self.client.session.subscribe_resource(TRANSCRIPT_URL)

            self._track_task(asyncio.create_task(_subscribe()))
        else:
            self._utterance_callbacks.add(callback)

        def remove_callback() -> None:
            """Remove the callback from the utterance callbacks."""
            self._utterance_callbacks.discard(callback)
            if (
                self._client is not None
                and not self._utterance_callbacks
                and is_async_context()
            ):
                self._track_task(
                    asyncio.create_task(
                        self._client.session.unsubscribe_resource(TRANSCRIPT_URL)
                    )
                )

        return remove_callback

    def add_segment_callback(
        self, callback: Callable[[list[TranscriptSegment]], Coroutine[None, None, None]]
    ) -> Callable[[], None]:
        """Add a callback to be called on segment events.

        Args:
            callback (Callable[[list[TranscriptSegment]], Coroutine[None, None, None]]):
                The callback to be called with new transcript segments.

        Returns:
            Callable[[], None]: A function to remove the callback.
        """
        if (
            self._client is not None
            and not self._segment_callbacks
            and is_async_context()
        ):
            # update last segment and subscribe
            async def _subscribe() -> None:
                await self._segment_update()
                self._segment_callbacks.add(callback)
                await self.client.session.subscribe_resource(SEGMENTS_URL)

            self._track_task(asyncio.create_task(_subscribe()))
        else:
            self._segment_callbacks.add(callback)

        def remove_callback() -> None:
            """Remove the callback from the segment callbacks."""
            self._segment_callbacks.discard(callback)
            if (
                self._client is not None
                and not self._segment_callbacks
                and is_async_context()
            ):
                self._track_task(
                    asyncio.create_task(
                        self._client.session.unsubscribe_resource(SEGMENTS_URL)
                    )
                )

        return remove_callback

    async def __aenter__(self) -> Self:
        """Connect to the joinly server."""
        await self._connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Disconnect from the joinly server."""
        self._utterance_callbacks.clear()
        self._segment_callbacks.clear()
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
            logger.debug("Connected to joinly server")

        if self._utterance_callbacks:
            await self._client.session.subscribe_resource(TRANSCRIPT_URL)
        if self._segment_callbacks:
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
        if not self.joined:
            return

        resource = await self.client.read_resource(TRANSCRIPT_URL)
        transcript = Transcript.model_validate_json(resource[0].text)  # type: ignore[attr-defined]
        new_transcript = transcript.with_role(SpeakerRole.participant).after(
            self._last_utterance
        )
        if new_transcript.segments and (
            not self.name_trigger or name_in_transcript(new_transcript, self.name)
        ):
            self._last_utterance = new_transcript.segments[-1].start
            for callback in self._utterance_callbacks:
                self._track_task(
                    asyncio.create_task(callback(new_transcript.compact().segments))
                )

    async def _segment_update(self) -> None:
        """Update the segment callback with new segments."""
        if not self.joined:
            return

        resource = await self.client.read_resource(SEGMENTS_URL)
        transcript = Transcript.model_validate_json(resource[0].text)  # type: ignore[attr-defined]
        new_transcript = transcript.after(self._last_segment)
        if new_transcript.segments:
            self._last_segment = new_transcript.segments[-1].start
            for callback in self._segment_callbacks:
                self._track_task(asyncio.create_task(callback(new_transcript.segments)))

    async def list_tools(self) -> list[Tool]:
        """List the available tools on the joinly server.

        Returns:
            list[Tool]: A list of available tools.
        """
        return await self.client.list_tools()

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
        logger.info("Joining meeting at %s", meeting_url)
        await self.client.call_tool(
            "join_meeting",
            arguments={
                "meeting_url": meeting_url,
                "passcode": passcode,
                "participant_name": self.name,
            },
        )
        logger.info("Joined meeting successfully")
        self.joined = True
        self._last_utterance = 0.0
        self._last_segment = 0.0

    async def leave_meeting(self) -> None:
        """Leave the current meeting."""
        if not self.joined:
            msg = "Not joined to a meeting"
            raise RuntimeError(msg)

        await self.client.call_tool("leave_meeting")
        self.joined = False
        self._last_utterance = 0.0
        self._last_segment = 0.0

    async def get_transcript(self) -> Transcript:
        """Get the full transcript from the server.

        Returns:
            Transcript: The current transcript.
        """
        if not self.joined:
            return Transcript(segments=[])

        result = await self.client.call_tool("get_transcript")
        return Transcript.model_validate_json(result.content[0].text)  # type: ignore[attr-defined]

    async def get_chat_history(self) -> MeetingChatHistory:
        """Get the chat history of the meeting.

        Returns:
            MeetingChatHistory: The chat history of the meeting.
        """
        if not self.joined:
            return MeetingChatHistory(messages=[])

        result = await self.client.call_tool("get_chat_history")
        return MeetingChatHistory.model_validate_json(result.content[0].text)  # type: ignore[attr-defined]

    async def get_participants(self) -> MeetingParticipantList:
        """Get the list of participants in the meeting.

        Returns:
            MeetingParticipantList: The list of participants.
        """
        if not self.joined:
            return MeetingParticipantList()

        result = await self.client.call_tool("get_participants")
        return MeetingParticipantList.model_validate_json(result.content[0].text)  # type: ignore[attr-defined]

    async def get_usage(self) -> Usage:
        """Get the current usage statistics from the server.

        Returns:
            Usage: The current usage statistics.
        """
        try:
            result = await self.client.read_resource(USAGE_URL)
        except McpError:
            logger.warning("Failed to get usage statistics")
            return Usage()
        else:
            return Usage.model_validate_json(result[0].text)  # type: ignore[attr-defined]

    async def speak_text(self, text: str) -> None:
        """Speak the given text using the joinly server.

        Args:
            text (str): The text to speak.
        """
        if not self.joined:
            msg = "Not joined to a meeting"
            raise RuntimeError(msg)

        await self.client.call_tool(
            "speak_text",
            arguments={"text": text},
        )

    async def send_chat_message(self, message: str) -> None:
        """Send a chat message in the meeting.

        Args:
            message (str): The chat message to send.
        """
        if not self.joined:
            msg = "Not joined to a meeting"
            raise RuntimeError(msg)

        await self.client.call_tool(
            "send_chat_message",
            arguments={"message": message},
        )

    async def mute(self) -> None:
        """Mute the participant in the meeting."""
        if not self.joined:
            msg = "Not joined to a meeting"
            raise RuntimeError(msg)

        await self.client.call_tool("mute_yourself")

    async def unmute(self) -> None:
        """Unmute the participant in the meeting."""
        if not self.joined:
            msg = "Not joined to a meeting"
            raise RuntimeError(msg)

        await self.client.call_tool("unmute_yourself")
