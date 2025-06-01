import asyncio
import contextlib
import logging
import sys
from typing import Any

from dotenv import load_dotenv
from fastmcp import Client
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode, create_react_agent
from mcp import ResourceUpdatedNotification, ServerNotification
from pydantic import AnyUrl

from joinly.server import mcp
from joinly.settings import get_settings
from joinly.types import Transcript

logger = logging.getLogger(__name__)


def format_messages(messages: list[BaseMessage]) -> str:
    """Format messages for logging."""
    m_str = []
    for m in messages:
        s = f"{m.type} ({m.name}): {m.content}" if m.name else f"{m.type}: {m.content}"
        if (
            hasattr(m, "additional_kwargs")
            and m.additional_kwargs
            and (tools := m.additional_kwargs.get("tool_calls"))
        ):
            tool_str = [
                f"{t['function']['name']}: {t['function']['arguments']}" for t in tools
            ]
            s += f" ({', '.join(tool_str)})"
        m_str.append(s)
    return "\n".join(m_str)


class PromptLogger(BaseCallbackHandler):
    """Callback that logs the exact prompt the model receives."""

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],  # noqa: ARG002
        messages: list[list[BaseMessage]],
        **_: Any,  # noqa: ANN401
    ) -> None:
        """Log the prompt the model receives."""
        logger.info("PROMPT\n%s", format_messages([m for b in messages for m in b]))


def get_new_messages(
    transcript: Transcript, old_transcript: Transcript | None = None
) -> list[HumanMessage]:
    """Convert a transcript to a list of HumanMessage.

    Optionally, only include new messages since the last transcript.
    """
    start_ind = 0 if old_transcript is None else len(old_transcript.segments)
    return [
        HumanMessage(
            content=segment.text,
            name=segment.speaker if segment.speaker is not None else "Unknown",
        )
        for segment in transcript.segments[start_ind:]
    ]


async def run(meeting_url: str | None = None) -> None:
    """Simple conversational agent for a meeting."""
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

    llm = AzureChatOpenAI(
        azure_deployment="gpt-4o-mini",
        api_version="2024-12-01-preview",
    )

    prompt = (
        "You are a helpful assistant in a meeting. "
        "Be formal and concise. "
        "You will receive messages from the meeting transcript. "
        "Your task is to respond to the messages as they come in. "
        "You can ask questions, provide information, or summarize the meeting. "
        "You should not provide any personal opinions or make any decisions. "
        "You should only respond to the messages you receive. "
        "You should not ask for clarification or provide any additional information. "
        "Do not use normal messages but the tools provided to you. "
        "If interrupted, stop your response."
    )

    client = Client(mcp, message_handler=_message_handler)

    async with client:
        await client.session.subscribe_resource(transcript_url)

        tools = await load_mcp_tools(client.session)
        tool_node = ToolNode(tools, handle_tool_errors=lambda e: e)
        memory = MemorySaver()
        prompt_logger = PromptLogger()
        llm_binded = llm.bind_tools(tools, tool_choice="auto")
        agent = create_react_agent(
            llm_binded, tool_node, prompt=prompt, checkpointer=memory
        )
        old_transcript = None

        await client.call_tool(
            "join_meeting",
            {"meeting_url": meeting_url, "participant_name": settings.name},
        )

        try:
            while True:
                await transcript_event.wait()
                transcript = Transcript.model_validate_json(
                    (await client.read_resource(transcript_url))[0].text  # type: ignore[attr-defined]
                )
                transcript_event.clear()

                async for chunk in agent.astream(
                    {"messages": get_new_messages(transcript, old_transcript)},
                    config={
                        "callbacks": [prompt_logger],
                        "configurable": {"thread_id": "1"},
                    },
                    stream_mode="updates",
                ):
                    if "agent" in chunk:
                        logger.info(
                            "AGENT\n%s", format_messages(chunk["agent"]["messages"])
                        )
                    elif "tools" in chunk:
                        logger.info(
                            "TOOLS\n%s", format_messages(chunk["tools"]["messages"])
                        )

                old_transcript = transcript

        finally:
            with contextlib.suppress(Exception):
                await client.call_tool("leave_meeting")


if __name__ == "__main__":
    load_dotenv()

    logging.basicConfig(level=logging.INFO)

    meeting_url = sys.argv[1] if len(sys.argv) > 1 else None

    asyncio.run(run(meeting_url=meeting_url))
