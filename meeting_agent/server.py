import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastmcp import Context, FastMCP
from mcp.server import NotificationOptions
from pydantic import AnyUrl, Field

from meeting_agent.session import MeetingSession, MeetingSessionConfig
from meeting_agent.types import Transcript

if TYPE_CHECKING:
    from mcp import ServerSession

logger = logging.getLogger(__name__)

SESSION_CONFIG: dict = {}


transcript_url = AnyUrl("transcript://live")


@dataclass
class SessionContext:
    """Context for the meeting session."""

    meeting_session: MeetingSession


@asynccontextmanager
async def session_lifespan(server: FastMCP) -> AsyncIterator[SessionContext]:
    """Create and enter a MeetingSession once per client connection."""
    logger.info("Creating meeting session")
    ms = MeetingSession(MeetingSessionConfig(**SESSION_CONFIG))
    await ms.__aenter__()

    _removers: dict[ServerSession, Callable[[], None]] = {}

    @server._mcp_server.subscribe_resource()  # noqa: SLF001
    async def _handle_subscribe_resource(url: AnyUrl) -> None:
        if url != transcript_url:
            return
        logger.info("Subscribing to resource: %s", url)
        session = server._mcp_server.request_context.session  # noqa: SLF001

        async def _push(event: str, text: str) -> None:
            if event == "segment":
                logger.debug("Sending transcription update notification for: %s", text)
                await session.send_resource_updated(transcript_url)

        _removers[session] = ms.add_transcription_listener(_push)

    @server._mcp_server.unsubscribe_resource()  # noqa: SLF001
    async def _handle_unsubscribe_resource(url: AnyUrl) -> None:
        session = server._mcp_server.request_context.session  # noqa: SLF001
        if url == transcript_url and (rem := _removers.pop(session, None)):
            logger.info("Unsubscribing from resource: %s", url)
            rem()

    try:
        yield SessionContext(meeting_session=ms)
    finally:
        for rem in _removers.values():
            rem()

        # ensure proper cleanup
        from anyio import CancelScope

        with CancelScope(shield=True):
            await ms.__aexit__(None, None, None)


mcp = FastMCP(
    "meeting-agent-mcp",
    lifespan=session_lifespan,
    notification_options=NotificationOptions(resources_changed=True),
    capabilities={"resources": {"subscribe": True}},
)


@mcp.resource(
    "transcript://live",
    description="Live transcript of the meeting",
    mime_type="application/json",
)
async def get_transcript(ctx: Context) -> Transcript:
    """Get the live transcript of the meeting."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    return ms.transcript


@mcp.tool(
    "join_meeting",
    description="Join a meeting with the given URL and participant name.",
)
async def join_meeting(
    meeting_url: Annotated[str, Field(description="URL to join an online meeting")],
    participant_name: Annotated[
        str | None, Field(description="Name of the participant to join as")
    ],
    ctx: Context,
) -> str:
    """Join a meeting with the given URL and participant name."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    await ms.join_meeting(meeting_url, participant_name)
    return "Joined meeting."


@mcp.tool(
    "leave_meeting",
    description="Leave the current meeting.",
)
async def leave_meeting(
    ctx: Context,
) -> str:
    """Leave the current meeting."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    await ms.leave_meeting()
    return "Left the meeting."


@mcp.tool(
    "speak_text",
    description="Speak the given text in the meeting using TTS.",
)
async def speak_text(
    text: Annotated[str, Field(description="Text to be spoken")],
    ctx: Context,
) -> str:
    """Speak the given text in the meeting using TTS."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    await ms.speak_text(text)
    return "Finished speaking."


@mcp.tool(
    "send_chat_message",
    description="Send a chat message in the meeting.",
)
async def send_chat_message(
    message: Annotated[str, Field(description="Message to be sent")],
    ctx: Context,
) -> str:
    """Send a chat message in the meeting."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    await ms.send_chat_message(message)
    return "Sent message."


@mcp.tool(
    "start_screen_sharing",
    description="Start screen sharing in the meeting.",
)
async def start_screen_sharing(
    ctx: Context,
) -> str:
    """Start screen sharing in the meeting."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    await ms.start_screen_sharing()
    return "Started screen sharing."


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
