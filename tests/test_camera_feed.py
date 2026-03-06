"""Manual camera feed test — cycles through all status effects.

Joins a meeting and triggers each action so the camera feed
animations can be visually inspected (e.g. via VNC).

Usage::

    JOINLY_TEST_MEETING_URL="https://..." \
        uv run pytest -m manual tests/test_camera_feed.py -v

Against a running server::

    JOINLY_TEST_MEETING_URL="https://..." \
    JOINLY_TEST_URL="http://localhost:8000/mcp" \
        uv run pytest -m manual tests/test_camera_feed.py -v
"""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from fastmcp import Client

from joinly.settings import Settings, set_settings

MEETING_URL = os.environ.get("JOINLY_TEST_MEETING_URL")
JOINLY_TEST_URL = os.environ.get("JOINLY_TEST_URL")

pytestmark = pytest.mark.manual

WAIT = 2


@pytest.fixture(scope="module", autouse=True)
def _settings() -> None:
    """Configure minimal settings for manual tests."""
    if not JOINLY_TEST_URL:
        set_settings(Settings(name="joinly", vad="webrtc", stt="whisper", tts="kokoro"))


@pytest.fixture(scope="module")
async def client() -> AsyncIterator[Client]:
    """Create a connected MCP client for the test module."""
    if JOINLY_TEST_URL:
        async with Client(JOINLY_TEST_URL) as c:
            yield c
    else:
        from joinly.server import mcp

        async with Client(mcp) as c:
            yield c


@pytest.mark.skipif(not MEETING_URL, reason="JOINLY_TEST_MEETING_URL not set")
async def test_camera_feed_effects(client: Client) -> None:
    """Join a meeting and cycle through all camera feed effects."""
    await client.call_tool(
        "join_meeting",
        arguments={"meeting_url": MEETING_URL},
    )
    await asyncio.sleep(15)

    try:
        await client.call_tool("unmute_yourself")
        await asyncio.sleep(WAIT)
        await client.call_tool(
            "speak_text",
            arguments={"text": "Testing the speaking animation on the camera feed."},
        )
        await asyncio.sleep(WAIT)

        await client.call_tool(
            "send_chat_message",
            arguments={"message": "camera feed test"},
        )
        await asyncio.sleep(WAIT)

        await client.call_tool("get_chat_history")
        await asyncio.sleep(WAIT)

        await client.call_tool("get_participants")
        await asyncio.sleep(WAIT)

        await client.call_tool(
            "share_screen",
            arguments={
                "url": "data:text/html,<html><body style='margin:0;"
                "background:%230066ff'></body></html>",
            },
        )
        await asyncio.sleep(WAIT)
        await client.call_tool("stop_sharing")
        await asyncio.sleep(WAIT)

    finally:
        await client.call_tool("leave_meeting")
