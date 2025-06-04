# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "langchain",
#     "langchain-mcp-adapters",
#     "langchain-openai",
#     "langgraph",
#     "mcp",
#     "py-dotenv",
#     "rich",
# ]
# ///

import asyncio
import contextlib
import datetime
import json
import logging
import sys

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode, create_react_agent
from mcp import ClientSession, ResourceUpdatedNotification, ServerNotification
from mcp.client.streamable_http import streamablehttp_client
from pydantic import AnyUrl, BaseModel

logger = logging.getLogger(__name__)


class TranscriptSegment(BaseModel):
    """A segment of a transcript."""

    text: str
    start: float
    end: float
    speaker: str | None = None


class Transcript(BaseModel):
    """A transcript containing multiple segments."""

    segments: list[TranscriptSegment]


def transcript_to_messages(transcript: Transcript) -> list[HumanMessage]:
    """Convert a transcript to a list of HumanMessage."""
    return [
        HumanMessage(
            content=s.text,
            name=s.speaker if s.speaker is not None else "Unknown",
        )
        for s in transcript.segments
    ]


def transcript_after(transcript: Transcript, after: float) -> Transcript:
    """Get a new transcript including only segments starting after given time."""
    segments = [s for s in transcript.segments if s.start > after]
    return Transcript(segments=segments)


async def run(  # noqa: C901
    mcp_url: str,
    meeting_url: str,
    model_name: str,
    model_provider: str | None = None,
) -> None:
    """Simple conversational agent for a meeting.

    Args:
        mcp_url: The URL of the MCP server.
        meeting_url: The URL of the meeting to join.
        model_name: The model to use for the agent.
        model_provider: The provider for the model.
    """
    transcript_url = AnyUrl("transcript://live")
    transcript_event = asyncio.Event()

    async def _message_handler(message) -> None:  # noqa: ANN001
        if (
            isinstance(message, ServerNotification)
            and isinstance(message.root, ResourceUpdatedNotification)
            and message.root.params.uri == transcript_url
        ):
            transcript_event.set()

    llm = init_chat_model(model_name, model_provider=model_provider)

    prompt = (
        f"Today is {datetime.datetime.now(tz=datetime.UTC).strftime('%d.%m.%Y')}. "
        "You are a professional and knowledgeable meeting assistant named joinly. "
        "Provide concise, valuable contributions to the meeting discussions. "
        "You receive real-time transcripts from the ongoing meeting. "
        "Respond thoughtfully when appropriate, but avoid unnecessary interruptions. "
        "Use available tools when needed to assist participants. "
        "Always finish your response with the 'finish' tool. "
        "If nothing requires your input, use the 'finish' tool immediately. "
        "If interrupted mid-response, gracefully conclude and use 'finish'."
    )

    async with (
        streamablehttp_client(mcp_url) as (read_stream, write_stream, _),
        ClientSession(
            read_stream, write_stream, message_handler=_message_handler
        ) as session,
    ):
        logger.info("Connecting to MCP server at %s", mcp_url)
        await session.initialize()
        logger.info("Connected to MCP server")
        await session.subscribe_resource(transcript_url)

        @tool(return_direct=True)
        def finish() -> str:
            """Finish tool to end the turn."""
            return "Finished."

        tools = [finish]
        tools.extend(await load_mcp_tools(session))
        tool_node = ToolNode(tools, handle_tool_errors=lambda e: e)
        llm_binded = llm.bind_tools(tools, tool_choice="required")

        memory = MemorySaver()
        agent = create_react_agent(
            llm_binded, tool_node, prompt=prompt, checkpointer=memory
        )
        last_time = -1.0

        logger.info("Joining meeting at %s", meeting_url)
        await session.call_tool(
            "join_meeting", {"meeting_url": meeting_url, "participant_name": "joinly"}
        )
        logger.info("Joined meeting successfully")

        try:
            while True:
                await transcript_event.wait()
                resource = await session.read_resource(transcript_url)
                transcript = transcript_after(
                    Transcript.model_validate_json(resource.contents[0].text),  # type: ignore[attr-defined]
                    after=last_time,
                )
                transcript_event.clear()
                if not transcript.segments:
                    logger.warning("No new segments in the transcript after update")
                    continue

                last_time = transcript.segments[-1].end
                for segment in transcript.segments:
                    logger.info(
                        '%s: "%s"',
                        segment.speaker if segment.speaker else "User",
                        segment.text,
                    )

                async for chunk in agent.astream(
                    {"messages": transcript_to_messages(transcript)},
                    config={"configurable": {"thread_id": "1"}},
                    stream_mode="updates",
                ):
                    if "agent" in chunk:
                        for m in chunk["agent"]["messages"]:
                            for t in m.additional_kwargs.get("tool_calls", []):
                                args_str = ", ".join(
                                    f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
                                    for k, v in json.loads(
                                        t["function"]["arguments"]
                                    ).items()
                                )
                                logger.info("%s: %s", t["function"]["name"], args_str)
                    if "tools" in chunk:
                        for m in chunk["tools"]["messages"]:
                            logger.info("%s: %s", m.name, m.content)

        finally:
            with contextlib.suppress(Exception):
                await session.call_tool("leave_meeting")


if __name__ == "__main__":
    load_dotenv()
    from rich.logging import RichHandler

    logging.basicConfig(
        level=logging.WARNING,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )
    logger.setLevel(logging.INFO)

    if len(sys.argv) not in (3, 4, 5):
        logger.error(
            "Usage: uv run basic_langchain.py <mcp_url> <meeting_url> "
            "[model_name] [model_provider]\n"
            "Example: uv run basic_langchain.py http://localhost:8000/mcp/ "
            "https://join.meeting.url gpt-4o azure_openai"
        )
        sys.exit(1)

    mcp_url = sys.argv[1]
    meeting_url = sys.argv[2]
    model_name = sys.argv[3] if len(sys.argv) == 4 else "gpt-4o"  # noqa: PLR2004
    model_provider = sys.argv[4] if len(sys.argv) == 5 else None  # noqa: PLR2004

    asyncio.run(
        run(
            mcp_url=mcp_url,
            meeting_url=meeting_url,
            model_name=model_name,
            model_provider=model_provider,
        )
    )
