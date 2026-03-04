"""Manual screen sharing tests.

These tests require a real meeting URL and human interaction (admitting the
bot into the meeting).  They are excluded from the default pytest run and can
be invoked explicitly::

    JOINLY_TEST_MEETING_URL="https://..." uv run pytest tests/test_screen_share.py
"""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from fastmcp import Client

from joinly.server import mcp
from joinly.settings import Settings, set_settings

MEETING_URL = os.environ.get("JOINLY_TEST_MEETING_URL")
SHARE_URL = os.environ.get(
    "JOINLY_TEST_SHARE_URL",
    "https://en.wikipedia.org/wiki/Screen_sharing",
)

pytestmark = pytest.mark.manual


@pytest.fixture(scope="module", autouse=True)
def _settings() -> None:
    """Configure minimal settings for manual tests."""
    set_settings(Settings(name="joinly", vad="webrtc", stt="whisper", tts="kokoro"))


@pytest.fixture(scope="module")
async def client() -> AsyncIterator[Client]:
    """Create a connected MCP client for the test module."""
    async with Client(mcp) as c:
        yield c


@pytest.mark.skipif(not MEETING_URL, reason="JOINLY_TEST_MEETING_URL not set")
async def test_share_screen(client: Client) -> None:
    """Join a meeting, share a URL, then stop and leave."""
    await client.call_tool(
        "join_meeting",
        arguments={"meeting_url": MEETING_URL},
    )

    await asyncio.sleep(15)

    await client.call_tool(
        "share_screen",
        arguments={"url": SHARE_URL},
    )

    await asyncio.sleep(30)

    await client.call_tool("stop_sharing")
    await client.call_tool("leave_meeting")
