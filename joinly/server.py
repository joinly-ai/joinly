import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import AnyUrl, Field, ValidationError

from joinly.container import SessionContainer
from joinly.session import MeetingSession
from joinly.settings import Settings, get_settings, reset_settings, set_settings
from joinly.types import (
    MeetingChatHistory,
    MeetingParticipant,
    SpeakerRole,
    SpeechInterruptedError,
    Transcript,
)

logger = logging.getLogger(__name__)

transcript_url = AnyUrl("transcript://live")


@dataclass
class SessionContext:
    """Context for the meeting session."""

    meeting_session: MeetingSession


def _extract_settings() -> Settings:
    """Extract settings from the HTTP headers."""
    current = get_settings()
    header = get_http_headers().get("joinly-settings")
    if not header:
        return current

    try:
        patch: Settings = Settings.model_validate(json.loads(header))
        settings = current.model_copy(update=patch.model_dump(exclude_unset=True))
    except (json.JSONDecodeError, ValidationError):
        msg = "Invalid joinly-settings."
        logger.exception(msg)
        logger.warning("Continuing with current settings")
        return current

    return settings


@asynccontextmanager
async def session_lifespan(server: FastMCP) -> AsyncIterator[SessionContext]:
    """Create and enter a MeetingSession once per client connection."""
    logger.info("Creating meeting session")
    settings = _extract_settings()
    settings_token = set_settings(settings)
    session_container = SessionContainer()
    meeting_session = await session_container.__aenter__()

    _remover: Callable[[], None] | None = None

    @server._mcp_server.subscribe_resource()  # noqa: SLF001
    async def _handle_subscribe_resource(url: AnyUrl) -> None:
        nonlocal _remover
        if url != transcript_url and _remover is not None:
            return
        logger.info("Subscribing to resource: %s", url)
        session = server._mcp_server.request_context.session  # noqa: SLF001

        async def _push(event: str) -> None:
            if event == "utterance":
                logger.debug("Sending transcription update notification")
                await session.send_resource_updated(transcript_url)

        _remover = meeting_session.add_transcription_listener(_push)

    @server._mcp_server.unsubscribe_resource()  # noqa: SLF001
    async def _handle_unsubscribe_resource(url: AnyUrl) -> None:
        if url == transcript_url and _remover is not None:
            logger.info("Unsubscribing from resource: %s", url)
            _remover()

    try:
        yield SessionContext(meeting_session=meeting_session)
    finally:
        if _remover is not None:
            _remover()

        # ensure proper cleanup
        from anyio import CancelScope

        with CancelScope(shield=True):
            await session_container.__aexit__()

        reset_settings(settings_token)


mcp = FastMCP("joinly", lifespan=session_lifespan)


@mcp.resource(
    "transcript://live",
    description="Live transcript of the meeting",
    mime_type="application/json",
)
async def get_transcript(ctx: Context) -> Transcript:
    """Get the live transcript of the meeting."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    return ms.transcript.with_role(SpeakerRole.participant)


@mcp.tool(
    "join_meeting",
    description="Join a meeting with the given URL and participant name.",
)
async def join_meeting(
    ctx: Context,
    meeting_url: Annotated[
        str | None, Field(default=None, description="URL to join an online meeting")
    ],
    participant_name: Annotated[
        str | None,
        Field(default=None, description="Name of the participant to join as"),
    ],
    passcode: Annotated[
        str | None,
        Field(
            default=None,
            description="Password or passcode for the meeting (if required)",
        ),
    ] = None,
) -> str:
    """Join a meeting with the given URL and participant name."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    await ms.join_meeting(meeting_url, participant_name, passcode)
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
    ctx: Context,
    text: Annotated[str, Field(description="Text to be spoken")],
) -> str:
    """Speak the given text in the meeting using TTS."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    try:
        await ms.speak_text(text)
    except SpeechInterruptedError as e:
        return str(e)
    return "Finished speaking."


@mcp.tool(
    "send_chat_message",
    description="Send a chat message in the meeting.",
)
async def send_chat_message(
    ctx: Context,
    message: Annotated[str, Field(description="Message to be sent")],
) -> str:
    """Send a chat message in the meeting."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    await ms.send_chat_message(message)
    return "Sent message."


@mcp.tool(
    "get_chat_history",
    description="Get the chat history from the meeting.",
)
async def get_chat_history(
    ctx: Context,
) -> MeetingChatHistory:
    """Get the chat history from the meeting."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    return await ms.get_chat_history()


@mcp.tool(
    "get_transcript",
    description=(
        "Get the transcript of the meeting. By default, returns the full transcript. "
        "To get a slice, set mode to 'first' or 'latest' and provide a positive "
        "minutes value."
    ),
)
async def get_transcript_tool(
    ctx: Context,
    mode: Annotated[
        Literal["full", "first", "latest"],
        Field(
            default="full",
            description="Mode to get the transcript: 'full' for the entire transcript, "
            "'first' for the first N minutes, 'latest' for the last N minutes.",
        ),
    ] = "full",
    minutes: Annotated[
        int,
        Field(
            default=0,
            description="Number of minutes to slice the transcript. "
            "Only used if mode is 'first' or 'latest'.",
        ),
    ] = 0,
) -> Transcript:
    """Get the transcript of the meeting."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    if mode == "first":
        return ms.transcript.before(minutes * 60).compact()
    if mode == "latest":
        return ms.transcript.after(ms.meeting_seconds - minutes * 60).compact()
    return ms.transcript.compact()


@mcp.tool(
    "get_participants",
    description="Get the list of participants in the meeting.",
)
async def get_participants(
    ctx: Context,
) -> list[MeetingParticipant]:
    """Get the list of participants in the meeting."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    return await ms.get_participants()


@mcp.tool(
    "mute_yourself",
    description="Mute yourself in the meeting.",
)
async def mute_yourself(
    ctx: Context,
) -> str:
    """Mute yourself in the meeting."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    await ms.mute()
    return "Muted yourself."


@mcp.tool(
    "unmute_yourself",
    description="Unmute yourself in the meeting.",
)
async def unmute_yourself(
    ctx: Context,
) -> str:
    """Unmute yourself in the meeting."""
    ms: MeetingSession = ctx.request_context.lifespan_context.meeting_session
    await ms.unmute()
    return "Unmuted yourself."


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
