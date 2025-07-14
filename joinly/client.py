import asyncio
import datetime
import logging
import re
import unicodedata

from fastmcp import Client
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode, create_react_agent
from mcp import ResourceUpdatedNotification, ServerNotification
from pydantic import AnyUrl

from joinly.server import mcp
from joinly.settings import get_settings
from joinly.types import Transcript

logger = logging.getLogger(__name__)


def transcript_to_messages(transcript: Transcript) -> list[HumanMessage]:
    """Convert a transcript to a list of HumanMessage.

    Args:
        transcript: The transcript to convert.

    Returns:
        A list of HumanMessage objects representing the transcript segments.
    """

    def _normalize_speaker(speaker: str | None) -> str:
        if speaker is None:
            return "Unknown"
        speaker = re.sub(r"\s+", "_", speaker.strip())
        return re.sub(r"[<>\|\\\/]+", "", speaker)

    return [
        HumanMessage(
            content=s.text,
            name=_normalize_speaker(s.speaker),
        )
        for s in transcript.segments
    ]


def transcript_after(transcript: Transcript, after: float) -> Transcript:
    """Get a new transcript including only segments starting after given time.

    Args:
        transcript: The original transcript.
        after: The time (seconds) after which to include segments.

    Returns:
        A new Transcript object containing only segments that start
            after the specified time.
    """
    segments = [s for s in transcript.segments if s.start > after]
    return Transcript(segments=segments)


def normalize(s: str) -> str:
    """Normalize a string.

    Args:
        s: The string to normalize.

    Returns:
        The normalized string.
    """
    normalized = unicodedata.normalize("NFKD", s.casefold().strip())
    chars = (c for c in normalized if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s]", "", "".join(chars))


def name_in_transcript(transcript: Transcript, name: str) -> bool:
    """Check if the name is mentioned in the transcript.

    Args:
        transcript: The transcript to check.
        name: The name to look for.

    Returns:
        True if the name is mentioned in the transcript, False otherwise.
    """
    pattern = rf"\b{re.escape(normalize(name))}\b"
    return bool(re.search(pattern, normalize(transcript.text)))


def log_chunk(chunk) -> None:  # noqa: ANN001
    """Log an update chunk from langgraph."""
    if "agent" in chunk:
        for m in chunk["agent"]["messages"]:
            for t in m.tool_calls or []:
                args_str = ", ".join(
                    f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
                    for k, v in t.get("args", {}).items()
                )
                logger.info("%s: %s", t["name"], args_str)
    if "tools" in chunk:
        for m in chunk["tools"]["messages"]:
            logger.info("%s: %s", m.name, m.content)


async def run(
    *,
    meeting_url: str | None = None,
    model_name: str = "gpt-4o",
    model_provider: str | None = None,
    name_trigger: bool = False,
) -> None:
    """Simple conversational agent for a meeting.

    Args:
        meeting_url: The URL of the meeting to join.
        model_name: The model to use for the agent.
        model_provider: The provider for the model.
        name_trigger: If True, the agent will only respond if its name is mentioned.
    """
    settings = get_settings()
    transcript_url = AnyUrl("transcript://live")
    transcript_event = asyncio.Event()

    async def _message_handler(message) -> None:  # noqa: ANN001
        if (
            isinstance(message, ServerNotification)
            and isinstance(message.root, ResourceUpdatedNotification)
            and message.root.params.uri == transcript_url
        ):
            logger.info("Transcription update received")
            transcript_event.set()

    llm = init_chat_model(model_name, model_provider=model_provider)

    prompt = (
        f"Today is {datetime.datetime.now(tz=datetime.UTC).strftime('%d.%m.%Y')}. "
        f"You are {settings.name}, a professional and knowledgeable meeting assistant. "
        "Provide concise, valuable contributions in the meeting. "
        "You are only with one other participant in the meeting, therefore "
        "respond to all messages and questions. "
        "When you are greeted, respond politely in spoken language. "
        "Give information, answer questions, and fullfill tasks as needed. "
        "You receive real-time transcripts from the ongoing meeting. "
        "Respond interactively and use available tools to assist participants. "
        "Always finish your response with the 'finish' tool. "
        "Never directly use the 'finish' tool, always respond first and then use it. "
        "If interrupted mid-response, use 'finish'."
    )

    client = Client(mcp, message_handler=_message_handler)

    async with client:
        await client.session.subscribe_resource(transcript_url)

        @tool(return_direct=True)
        def finish() -> str:
            """Finish tool to end the turn."""
            return "Finished."

        tools = await load_mcp_tools(client.session)
        tools.append(finish)
        tool_node = ToolNode(tools, handle_tool_errors=lambda e: e)
        llm_binded = llm.bind_tools(tools, tool_choice="any")

        memory = MemorySaver()
        agent = create_react_agent(
            llm_binded, tool_node, prompt=prompt, checkpointer=memory
        )
        last_time = -1.0

        await client.call_tool(
            "join_meeting",
            {"meeting_url": meeting_url, "participant_name": settings.name},
        )

        while True:
            await transcript_event.wait()
            transcript_full = Transcript.model_validate_json(
                (await client.read_resource(transcript_url))[0].text  # type: ignore[attr-defined]
            )
            transcript = transcript_after(transcript_full, after=last_time)
            transcript_event.clear()
            if not transcript.segments:
                logger.warning("No new segments in the transcript after update")
                continue

            if name_trigger and not name_in_transcript(transcript, settings.name):
                continue

            last_time = transcript.segments[-1].start
            for segment in transcript.segments:
                logger.info(
                    '%s: "%s"',
                    segment.speaker if segment.speaker else "User",
                    segment.text,
                )

            try:
                async for chunk in agent.astream(
                    {"messages": transcript_to_messages(transcript)},
                    config={"configurable": {"thread_id": "1"}},
                    stream_mode="updates",
                ):
                    log_chunk(chunk)
            except Exception:
                logger.exception("Error during agent invocation")
