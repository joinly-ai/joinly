import asyncio
import contextlib
import logging
import sys

from fastmcp import Client
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent
from mcp import ResourceUpdatedNotification, ServerNotification
from pydantic import AnyUrl

from meeting_agent.server import SESSION_CONFIG, mcp

logger = logging.getLogger(__name__)


async def run() -> None:
    """Main function to join a meeting and receive transcription updates."""
    transcript_url = AnyUrl("transcript://live")
    update_queue = asyncio.Queue()
    segment_queue = asyncio.Queue()

    async def _handler(message) -> None:  # noqa: ANN001
        if (
            isinstance(message, ServerNotification)
            and isinstance(message.root, ResourceUpdatedNotification)
            and message.root.params.uri == transcript_url
        ):
            logger.info("Transcription update received")
            await update_queue.put(None)

    async def _worker(client: Client) -> None:
        transcript = ""
        while True:
            await update_queue.get()
            new_transcript = (await client.read_resource(transcript_url))[0].text  # type: ignore[attr-defined]
            new_segment = new_transcript[len(transcript) :].strip()
            if len(new_segment) > 10:  # noqa: PLR2004
                logger.info("New segment: %s", new_segment)
                await segment_queue.put(new_segment)
            transcript = new_transcript

    llm = AzureChatOpenAI(
        azure_deployment="gpt-4o-mini",
        api_version="2024-12-01-preview",
    )

    prompt_blair = """You are Blair, the character of the series gossip girl.
    You are a smart and witty assistant. You are in a meeting with your boss,
    who is a bit clueless.
    You are taking notes and trying to make sense of the conversation.
    You are also trying to help your boss understand the conversation.
    You are a bit sarcastic and you like to make fun of your boss.
    You are also a bit of a gossip and you like to share juicy details about the people
    in the meeting.
    You are in a meeting with Dan Humphrey, who is a bit clueless and doesn't understand
    what is going on.
    IMPORTANT: Do not provide any normal messages. All interactions should be done using
    either the speak_text or the send_text_message tools. Dan can only hear you if you
    use the speak_text tool.
    """

    prompt_dan = """You are Dan Humphrey, the character of the series gossip girl.
    You are a bit clueless and don't understand what is going on in the meeting.
    You are trying to keep up with the conversation, but you often miss important
    details.
    You rely on Blair to help you understand the situation. However, you hate her.
    IMPORTANT: Do not provide any normal messages. All interactions should be done using
    either the speak_text or the send_text_message tools. Blair can only hear you if you
    use the speak_text tool.
    """  # noqa: F841

    client = Client(mcp, message_handler=_handler)

    async with client:
        await client.session.subscribe_resource(transcript_url)

        worker_task = asyncio.create_task(_worker(client))

        tools = await load_mcp_tools(client.session)
        agent = create_react_agent(llm, tools, prompt=prompt_blair)

        await asyncio.sleep(15)

        await client.call_tool(
            "speak_text",
            {"text": "Hello, I am Blair. Who are you?"},
        )

        try:
            while True:
                new_segment = await segment_queue.get()
                logger.info("New segment: %s", new_segment)

                async for chunk in agent.astream(
                    {
                        "messages": 'In the meeting was said: "'
                        + new_segment
                        + '". Act accordingly.'
                    },
                    stream_mode="updates",
                ):
                    logger.info(chunk)
        finally:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task


if __name__ == "__main__":
    if len(sys.argv) != 2:  # noqa: PLR2004
        logger.error("Usage: python client.py <meeting_url>")
        sys.exit(1)

    SESSION_CONFIG["meeting_url"] = sys.argv[1]
    asyncio.run(run())
