import asyncio
import logging
import sys

from fastmcp import Client
from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode, create_react_agent
from mcp import ResourceUpdatedNotification, ServerNotification
from pydantic import AnyUrl

from meeting_agent.server import SESSION_CONFIG, mcp
from meeting_agent.types import Transcript

logger = logging.getLogger(__name__)


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
            name=segment.speaker,
        )
        for segment in transcript.segments[start_ind:]
    ]


async def run() -> None:
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
    )

    client = Client(mcp, message_handler=_message_handler)

    try:
        async with client:
            await client.session.subscribe_resource(transcript_url)

            tools = await load_mcp_tools(client.session)
            tool_node = ToolNode(tools, handle_tool_errors=lambda e: e)
            memory = MemorySaver()
            agent = create_react_agent(
                llm, tool_node, prompt=prompt, checkpointer=memory
            )
            old_transcript = None

            while True:
                await transcript_event.wait()
                transcript = Transcript.model_validate_json(
                    (await client.read_resource(transcript_url))[0].text  # type: ignore[attr-defined]
                )
                transcript_event.clear()

                async for chunk in agent.astream(
                    {"messages": get_new_messages(transcript, old_transcript)},
                    config={"configurable": {"thread_id": "1"}},
                    stream_mode="updates",
                ):
                    logger.info(chunk)

                old_transcript = transcript
    except asyncio.CancelledError:
        await asyncio.sleep(5)


if __name__ == "__main__":
    if len(sys.argv) != 2:  # noqa: PLR2004
        logger.error("Usage: python client.py <meeting_url>")
        sys.exit(1)

    SESSION_CONFIG["meeting_url"] = sys.argv[1]
    asyncio.run(run())
