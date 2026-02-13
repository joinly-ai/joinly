# ruff: noqa: T201, S101, PLR2004, D103, S108
"""Quick integration test: join a meeting and trigger screen sharing.

Usage (must run inside Docker or a Linux env with Xvfb + PulseAudio):

    uv run python scripts/test_screen_share.py <meeting-url> [url-to-share]

Examples:
    uv run python scripts/test_screen_share.py https://meet.google.com/abc-defg-hij
    uv run python scripts/test_screen_share.py https://meet.google.com/abc-defg-hij https://example.com
"""

import asyncio
import base64
import logging
import sys
from pathlib import Path

from fastmcp import Client

from joinly.server import mcp
from joinly.settings import Settings, set_settings
from joinly.utils.logging import configure_logging

logger = logging.getLogger(__name__)


async def main(meeting_url: str, share_url: str | None = None) -> None:
    configure_logging(verbose=2, quiet=False, plain=True)
    set_settings(Settings(name="joinly", vad="webrtc", stt="whisper", tts="kokoro"))

    client = Client(mcp)

    async with client:
        # 1. List available tools
        tools = await client.list_tools()
        tool_names = [t.name for t in tools]
        logger.info("Available tools: %s", tool_names)
        assert "share_screen" in tool_names, "share_screen tool not registered"
        assert "stop_sharing" in tool_names, "stop_sharing tool not registered"

        # 2. Join the meeting
        logger.info("Joining meeting: %s", meeting_url)
        result = await client.call_tool(
            "join_meeting",
            {"meeting_url": meeting_url, "participant_name": "joinly"},
        )
        logger.info("Join result: %s", result)

        # 3. Wait for the bot to settle in
        logger.info("Waiting 10s for meeting to stabilise...")
        await asyncio.sleep(10)

        # 4. Take a snapshot before sharing
        logger.info("Taking pre-share snapshot...")
        snapshot = await client.call_tool("get_video_snapshot", {})
        logger.info("Pre-share snapshot: %s", snapshot)

        # 5. Try screen sharing
        share_args: dict[str, str] = {}
        if share_url:
            share_args["url"] = share_url
        logger.info("Starting screen share (url=%s)...", share_url)
        result = await client.call_tool("share_screen", share_args)
        logger.info("Share result: %s", result)

        if result.is_error:
            logger.error("Screen share failed: %s", result)
        else:
            logger.info("Sharing for 15s...")
            await asyncio.sleep(5)

            # Take a snapshot during sharing to debug what the display shows
            logger.info("Taking mid-share snapshot...")
            snapshot = await client.call_tool("get_video_snapshot", {})
            for item in snapshot.content:
                if hasattr(item, "data") and item.data:
                    img_bytes = base64.b64decode(item.data)
                    out = Path("/tmp/mid_share_snapshot.jpg")
                    out.write_bytes(img_bytes)
                    logger.info("Saved mid-share snapshot to %s", out)

            await asyncio.sleep(10)

            logger.info("Stopping screen share...")
            result = await client.call_tool("stop_sharing", {})
            logger.info("Stop result: %s", result)

        await asyncio.sleep(3)

        # 7. Leave
        logger.info("Leaving meeting...")
        result = await client.call_tool("leave_meeting", {})
        logger.info("Leave result: %s", result)

    logger.info("Done.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <meeting-url> [url-to-share]")
        sys.exit(1)

    meeting_url = sys.argv[1]
    share_url = sys.argv[2] if len(sys.argv) > 2 else None
    asyncio.run(main(meeting_url, share_url))
