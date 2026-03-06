"""End-to-end test with two bot instances in a real meeting.

Both bots join the same meeting and validate each other: participants,
chat, screen sharing, speech, transcription, snapshots, and more.
The only manual step is providing a meeting URL and admitting both bots.

Usage::

    JOINLY_TEST_MEETING_URL="https://..." \
        uv run pytest -m manual tests/test_e2e.py -v

Against running servers (e.g. Docker)::

    JOINLY_TEST_MEETING_URL="https://..." \
    JOINLY_TEST_URL_A="http://localhost:8000/mcp/" \
    JOINLY_TEST_URL_B="http://localhost:8001/mcp/" \
        uv run pytest -m manual tests/test_e2e.py -v
"""

import asyncio
import base64
import io
import os
from collections.abc import AsyncIterator

import pytest
from fastmcp import FastMCP
from joinly_client import JoinlyClient
from joinly_client.types import TranscriptSegment
from PIL import Image

MEETING_URL = os.environ.get("JOINLY_TEST_MEETING_URL")
JOINLY_TEST_URL_A = os.environ.get("JOINLY_TEST_URL_A")
JOINLY_TEST_URL_B = os.environ.get("JOINLY_TEST_URL_B")

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(not MEETING_URL, reason="JOINLY_TEST_MEETING_URL not set"),
]

BOT_A_NAME = "TestBot Alpha"
BOT_B_NAME = "TestBot Beta"
JOIN_WAIT = 20

# Solid red page used for screen share color verification
_RED_PAGE = (
    "data:text/html,<html><body style='margin:0;background:%23ff0000'></body></html>"
)


_mcp: FastMCP | None = None


def _server() -> FastMCP:
    """Return a shared in-process MCP server, lazily initialized."""
    global _mcp  # noqa: PLW0603
    if _mcp is None:
        from joinly.server import mcp
        from joinly.settings import Settings, set_settings

        set_settings(Settings(name="joinly", vad="webrtc", stt="whisper", tts="kokoro"))
        _mcp = mcp
    return _mcp


def _red_ratio(image_data: bytes) -> float:
    """Return the fraction of pixels that are near-pure red (R>225, G<30, B<30)."""
    img = Image.open(io.BytesIO(image_data)).convert("RGB")
    pixels = list(img.getdata())
    red_count = sum(
        1
        for r, g, b in pixels
        if r > 225 and g < 30 and b < 30  # noqa: PLR2004
    )
    return red_count / len(pixels)


async def _snapshot_image(bot: JoinlyClient) -> bytes:
    """Take a video snapshot and return the raw image bytes."""
    result = await bot.client.call_tool("get_video_snapshot")
    return base64.b64decode(result.content[0].data)  # type: ignore[union-attr]


async def _transcript_text(bot: JoinlyClient) -> str:
    """Get the full transcript text from a bot, lowercased."""
    transcript = await bot.get_transcript()
    return " ".join(s.text for s in transcript.segments).lower()


@pytest.fixture(scope="module")
async def bots() -> AsyncIterator[tuple[JoinlyClient, JoinlyClient]]:
    """Create, connect, and join two bot instances."""
    url_a = JOINLY_TEST_URL_A or _server()
    url_b = JOINLY_TEST_URL_B or _server()

    bot_a = JoinlyClient(url_a, name=BOT_A_NAME)
    bot_b = JoinlyClient(url_b, name=BOT_B_NAME)

    async with bot_a, bot_b:
        await asyncio.gather(
            bot_a.join_meeting(MEETING_URL),
            bot_b.join_meeting(MEETING_URL),
        )
        await asyncio.sleep(JOIN_WAIT)
        yield bot_a, bot_b
        await bot_a.leave_meeting()
        await bot_b.leave_meeting()


async def test_participants_see_each_other(
    bots: tuple[JoinlyClient, JoinlyClient],
) -> None:
    """Both bots should appear in each other's participant list."""
    bot_a, bot_b = bots

    participants_a = await bot_a.get_participants()
    participants_b = await bot_b.get_participants()

    names_a = {p.name for p in participants_a.root}
    names_b = {p.name for p in participants_b.root}

    assert BOT_A_NAME in names_b, f"Bot B doesn't see Bot A. Seen: {names_b}"
    assert BOT_B_NAME in names_a, f"Bot A doesn't see Bot B. Seen: {names_a}"
    assert len(participants_a.root) >= len(bots)
    assert len(participants_b.root) >= len(bots)


async def test_chat(
    bots: tuple[JoinlyClient, JoinlyClient],
) -> None:
    """Both bots exchange messages; both see them with sender attribution."""
    bot_a, bot_b = bots
    msg_a = f"from-alpha-{os.urandom(4).hex()}"
    msg_b = f"from-beta-{os.urandom(4).hex()}"

    await bot_a.send_chat_message(msg_a)
    await bot_b.send_chat_message(msg_b)
    await asyncio.sleep(3)

    history_a = await bot_a.get_chat_history()
    history_b = await bot_b.get_chat_history()
    texts_a = " ".join(m.text for m in history_a.messages)
    texts_b = " ".join(m.text for m in history_b.messages)

    assert msg_b in texts_a, f"Bot A didn't see Bot B's message: {texts_a}"
    assert msg_a in texts_b, f"Bot B didn't see Bot A's message: {texts_b}"

    matching = [m for m in history_b.messages if msg_a in m.text]
    assert matching[0].sender is not None, "Sender should not be None"


async def test_mute_prevents_transcription(
    bots: tuple[JoinlyClient, JoinlyClient],
) -> None:
    """Speech while muted should NOT appear in the other bot's transcript."""
    bot_a, bot_b = bots
    muted_phrase = "muted elephant purple"

    await bot_a.mute()
    await asyncio.sleep(1)
    await bot_a.speak_text(muted_phrase)
    await asyncio.sleep(10)

    text = await _transcript_text(bot_b)
    assert "elephant" not in text, f"Muted speech was transcribed: {text}"

    await bot_a.unmute()
    await asyncio.sleep(1)


async def test_unmute_allows_transcription(
    bots: tuple[JoinlyClient, JoinlyClient],
) -> None:
    """Speech after unmuting should appear in the other bot's transcript."""
    bot_a, bot_b = bots
    unmuted_phrase = "unmuted giraffe orange"

    await bot_a.unmute()
    await asyncio.sleep(1)
    await bot_a.speak_text(unmuted_phrase)
    await asyncio.sleep(15)

    text = await _transcript_text(bot_b)
    assert "giraffe" in text or "orange" in text, (
        f"Unmuted speech not transcribed: {text}"
    )


async def test_screen_share(
    bots: tuple[JoinlyClient, JoinlyClient],
) -> None:
    """Share red page, verify snapshot, stop, verify cleanup, re-share."""
    bot_a, bot_b = bots

    # stop when not sharing should be a no-op
    await bot_a.stop_sharing()

    # share red page and verify >30% near-pure red pixels
    await bot_a.share_screen(_RED_PAGE)
    await asyncio.sleep(8)
    ratio = _red_ratio(await _snapshot_image(bot_b))
    assert ratio > 0.3, f"Only {ratio:.0%} red pixels during share"  # noqa: PLR2004

    # stop and verify red is gone
    await bot_a.stop_sharing()
    await asyncio.sleep(5)
    ratio = _red_ratio(await _snapshot_image(bot_b))
    assert ratio < 0.05, f"Still {ratio:.0%} red after stop"  # noqa: PLR2004

    # re-share to verify share works again after stop
    await bot_a.share_screen(_RED_PAGE)
    await asyncio.sleep(5)
    ratio = _red_ratio(await _snapshot_image(bot_b))
    assert ratio > 0.3, f"Only {ratio:.0%} red on re-share"  # noqa: PLR2004
    await bot_a.stop_sharing()
    await asyncio.sleep(2)


async def test_speak_and_transcribe(
    bots: tuple[JoinlyClient, JoinlyClient],
) -> None:
    """Bot A speaks, Bot B transcribes with valid segments and speaker."""
    bot_a, bot_b = bots

    await bot_a.unmute()
    await asyncio.sleep(1)
    await bot_a.speak_text("The quick brown fox jumps over the lazy dog.")
    await asyncio.sleep(15)

    transcript = await bot_b.get_transcript()
    assert transcript.segments, "No transcript segments"

    full_text = " ".join(s.text for s in transcript.segments).lower()
    assert "fox" in full_text or "dog" in full_text, (
        f"Bot B didn't transcribe Bot A's speech: {full_text}"
    )

    speakers = {s.speaker for s in transcript.segments if s.speaker}
    assert speakers, f"No speaker attribution: {transcript.segments}"

    for seg in transcript.segments:
        assert seg.text.strip(), f"Empty segment text: {seg}"
        assert seg.start >= 0, f"Negative start: {seg}"
        assert seg.end >= seg.start, f"End before start: {seg}"


async def test_segment_callback_content(
    bots: tuple[JoinlyClient, JoinlyClient],
) -> None:
    """Segment callback should fire with content matching what was spoken."""
    bot_a, bot_b = bots

    received: list[list[TranscriptSegment]] = []

    async def _on_segments(segs: list[TranscriptSegment]) -> None:
        received.append(segs)

    remove = bot_b.add_segment_callback(_on_segments)

    try:
        await bot_a.speak_text("Banana strawberry watermelon.")
        for _ in range(30):
            if received:
                break
            await asyncio.sleep(1)

        assert received, "No segment callback received"
        all_text = " ".join(s.text for batch in received for s in batch).lower()
        assert any(
            word in all_text for word in ("banana", "strawberry", "watermelon")
        ), f"Callback text doesn't match spoken words: {all_text}"
    finally:
        remove()


async def test_video_snapshot_is_valid_image(
    bots: tuple[JoinlyClient, JoinlyClient],
) -> None:
    """Video snapshot should be a decodable JPEG image of reasonable size."""
    bot_a, _bot_b = bots

    img_bytes = await _snapshot_image(bot_a)
    img = Image.open(io.BytesIO(img_bytes))

    assert img.format == "JPEG", f"Expected JPEG, got {img.format}"
    assert img.size[0] > 0, f"Invalid width: {img.size}"
    assert img.size[1] > 0, f"Invalid height: {img.size}"
