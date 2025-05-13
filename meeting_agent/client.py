import logging
import sys

from fastmcp import Client
from mcp import ResourceUpdatedNotification, ServerNotification
from pydantic import AnyUrl

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def main(meeting_url: str) -> None:
    """Main function to join a meeting and receive transcription updates."""
    transcript_url = AnyUrl("transcript://live")

    async def _handler(message) -> None:  # noqa: ANN001
        if (
            isinstance(message, ServerNotification)
            and isinstance(message.root, ResourceUpdatedNotification)
            and message.root.params.uri == transcript_url
        ):
            logger.info("Transcription update received")

    client = Client("http://localhost:8000/mcp", message_handler=_handler)

    logger.info("Connecting to MCP server")
    async with client:
        logger.info("Connected to MCP server")
        logger.info("Subscribing to transcription resource: %s", transcript_url)
        await client.session.subscribe_resource(transcript_url)
        logger.info("Subscribed to transcription resource")
        logger.info("Joining meeting: %s", meeting_url)

        tools = await client.list_tools()
        logger.info("Available tools: %s", tools)

        await client.call_tool(
            "join_meeting",
            {
                "meeting_url": meeting_url,
                "participant_name": "joinly.ai",
            },
        )
        logger.info("Joined meeting")
        logger.info("Waiting for transcription updates...")

        await asyncio.sleep(60)


if __name__ == "__main__":
    import asyncio

    if len(sys.argv) != 2:  # noqa: PLR2004
        logger.error("Usage: python client.py <meeting_url>")
        sys.exit(1)

    meeting_url = sys.argv[1]
    asyncio.run(main(meeting_url))
