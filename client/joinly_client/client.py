import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from typing import Any, Self

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from mcp import ResourceUpdatedNotification, ServerNotification, Tool
from pydantic import AnyUrl

from joinly_client.types import SpeakerRole, Transcript, TranscriptSegment

logger = logging.getLogger(__name__)

TRANSCRIPT_URL = AnyUrl("transcript://live")


class JoinlyClient:
    """Client for interacting with the joinly server."""

    def __init__(
        self,
        joinly_url: str | FastMCP,
        *,
        name: str | None = None,
        name_trigger: bool = False,
        settings: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the JoinlyClient with the server URL.

        Args:
            joinly_url (str | FastMCP): The URL of the Joinly server or a
                FastMCP instance.
            name (str | None): The name of the participant, defaults to "joinly".
            name_trigger (bool): Whether to use name trigger for speech recognition.
            settings (dict[str, Any]): Additional settings for the client.
        """
        self.joinly_url = joinly_url
        self.name_trigger = name_trigger
        self.settings = settings or {}
        self.name = name or self.settings.get("name", "joinly")
        self.settings["name"] = self.name

        self._client: Client | None = None
        self._stack = AsyncExitStack()
        self._utterance_callback: (
            Callable[[list[TranscriptSegment]], Awaitable[None]] | None
        ) = None
        self._utterance_task: asyncio.Task | None = None
        self._last_segment: float = 0.0

    @property
    def client(self) -> Client:
        """Get the current client instance."""
        if self._client is None:
            msg = "Client is not connected"
            raise RuntimeError(msg)
        return self._client

    async def __aenter__(self) -> Self:
        """Connect to the joinly server."""
        await self._connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Disconnect from the joinly server."""
        await self._stack.aclose()
        self._client = None

    async def _connect(self) -> None:
        """Connect to the joinly server."""

        async def _message_handler(message) -> None:  # noqa: ANN001
            if (
                isinstance(message, ServerNotification)
                and isinstance(message.root, ResourceUpdatedNotification)
                and message.root.params.uri == TRANSCRIPT_URL
            ) and self._utterance_callback:
                if self._utterance_task is not None and not self._utterance_task.done():
                    self._utterance_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._utterance_task

                if new_segments := await self._get_new_segments():
                    self._utterance_task = asyncio.ensure_future(
                        self._utterance_callback(new_segments)
                    )

        if isinstance(self.joinly_url, str):
            transport = StreamableHttpTransport(
                url=self.joinly_url,
                headers={"joinly-settings": json.dumps(self.settings)},
            )
        else:
            transport = self.joinly_url

        self._client = Client(transport=transport, message_handler=_message_handler)

        logger.info("Connecting to joinly server at %s", self.joinly_url)
        try:
            await self._stack.enter_async_context(self.client)
            await self.client.session.subscribe_resource(TRANSCRIPT_URL)
        except Exception:
            logger.exception("Failed to connect to joinly server")
            await self._stack.aclose()
            raise
        else:
            logger.info("Connected to joinly server")

    async def list_tools(self) -> list[Tool]:
        """List available tools on the joinly server.

        Returns:
            list[Tool]: A list of available tools excluding the "join_meeting" tool.
        """
        tools = await self.client.list_tools()
        return [tool for tool in tools if tool.name != "join_meeting"]

    async def on_utterance(
        self, callback: Callable[[list[TranscriptSegment]], Awaitable[None]]
    ) -> None:
        """Set a callback to be called on utterance events.

        Args:
            callback (Callable[[list[TranscriptSegment]], Awaitable[None]]):
                The callback to be called with new transcript segments.
        """
        self._utterance_callback = callback

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
        self._last_segment = 0.0

    async def _get_new_segments(self) -> list[TranscriptSegment]:
        """Get new transcript segments from the server.

        Returns:
            list[TranscriptSegment]: A list of new transcript segments.
        """
        resource = await self.client.read_resource(TRANSCRIPT_URL)
        transcript = Transcript.model_validate(resource[0].text)  # type: ignore[attr-defined]
        new_transcript = (
            transcript.after(self._last_segment)
            .with_role(SpeakerRole.participant)
            .compact()
        )
        if not new_transcript.segments:
            return []
        self._last_segment = new_transcript.segments[-1].start
        return new_transcript.segments

    async def get_transcript(self) -> Transcript:
        """Get the current transcript from the server.

        Returns:
            Transcript: The current transcript.
        """
        result = await self.client.call_tool("get_transcript")
        return Transcript.model_validate(result.content[0].text)  # type: ignore[attr-defined]
