import asyncio
import contextlib
import datetime
import logging
import os
import sys
from typing import Any

from dotenv import load_dotenv
from fastmcp import Client
from langchain.tools import tool
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import AzureChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode, create_react_agent
from mcp import ResourceUpdatedNotification, ServerNotification
from notion_client import AsyncClient as NotionClient
from pydantic import AnyUrl

from joinly.server import mcp
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


async def run(
    meeting_url: str | None = None, participant_name: str | None = None
) -> None:
    """Simple conversational agent for a meeting."""
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
        azure_deployment="gpt-4.1",
        api_version="2024-12-01-preview",
    )

    search_tool = TavilySearch(max_results=5, topic="general")

    database_id = os.getenv("NOTION_DATABASE_ID")
    notion = os.getenv("NOTION_KEY")
    notion = NotionClient(auth=os.getenv("NOTION_KEY"))

    @tool
    async def notion_create_page(title: str, content: str) -> str:
        """Creates a new Notion page with the given title in the default database."""
        new_page = await notion.pages.create(
            parent={"database_id": database_id},
            properties={"Name": {"title": [{"text": {"content": title}}]}},
        )
        await notion.blocks.children.append(
            block_id=new_page["id"],
            children=[
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"text": {"content": content}}]},
                }
            ],
        )
        return f"Created page: {new_page['url']}"

    prompt = (
        f"Today is {datetime.datetime.now(tz=datetime.UTC).strftime('%d.%m.%Y')}. "
        "You are a helpful assistant in a meeting. "
        "Be formal and concise. "
        "You will receive transcripts as messages from the live meeting. "
        "Your task is to respond as a meeting participant using the speak tool "
        "and/or send message to the chat. "
        "Use the search tool to get up to date information where required. "
        "Never use normal messages but only the tools provided to you. "
        "If interrupted, stop your response."
    )

    client = Client(mcp, message_handler=_message_handler)

    async with client:
        await client.session.subscribe_resource(transcript_url)

        tools = await load_mcp_tools(client.session)
        tools.append(search_tool)
        tools.append(notion_create_page)
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
            {"meeting_url": meeting_url, "participant_name": participant_name},
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
    participant_name = sys.argv[2] if len(sys.argv) > 2 else "joinly"  # noqa: PLR2004

    asyncio.run(run(meeting_url=meeting_url, participant_name=participant_name))