import asyncio
from typing import Any

import jiwer
from mcp import ResourceUpdatedNotification, ServerNotification
from pydantic import AnyUrl

from meeting_agent.meeting_session import MeetingSession


async def test_meeting_transcription_mockup(meeting_mockup: dict[str, Any]) -> None:
    """Test transcription with meeting mockup."""
    await _run_meeting_transcription_test(
        meeting_url=meeting_mockup["url"],
        ground_truth_transcription=meeting_mockup["transcription"],
        duration_seconds=meeting_mockup["duration"] + 5,
    )


async def test_mcp_meeting_transcription_mockup(meeting_mockup: dict[str, Any]) -> None:
    """Test transcription with meeting mockup."""
    await _run_mcp_meeting_transcription_test(
        meeting_url=meeting_mockup["url"],
        ground_truth_transcription=meeting_mockup["transcription"],
        duration_seconds=meeting_mockup["duration"] + 5,
    )


async def _run_meeting_transcription_test(
    meeting_url: str,
    ground_truth_transcription: str,
    duration_seconds: int = 30,
    max_wer_threshold: float = 0.1,
) -> None:
    """Executes a meeting transcription test by joining a meeting and processing audio.

    This function sets up a test environment with browser, audio capture, VAD chunking,
    and transcription components to verify the audio transcription pipeline.

    Args:
        meeting_url: URL for the meeting to join
        ground_truth_transcription: Expected text in the transcription
        duration_seconds: How long to collect transcriptions (in seconds)
        max_wer_threshold: Maximum acceptable Word Error Rate (default 0.1 or 10%)
    """
    ms = MeetingSession(
        headless=True,
        use_browser_agent=False,
    )

    transcription_agg: list[str] = []

    async def _on_transcription(event: str, text: str) -> None:
        if event == "segment":
            transcription_agg.append(text)

    ms.add_transcription_listener(_on_transcription)

    async with ms:
        await ms.join_meeting(
            meeting_url=meeting_url,
            participant_name="Test Participant",
        )
        await asyncio.sleep(duration_seconds)

    assert transcription_agg, "No transcription received"
    transcription = " ".join(transcription_agg)
    assert transcription == ms.transcript, (
        "Transcription mismatch between aggregate and full transcript. "
        f"Expected: {ms.transcript}, Got: {transcription}"
    )

    wer = _calculate_wer(transcription, ground_truth_transcription)
    assert wer <= max_wer_threshold, (
        f"Transcription quality below threshold. WER: {wer:.2f}, "
        f"Max allowed: {max_wer_threshold:.2f}\n"
        f'Transcription: "{transcription}"\n'
        f'Ground truth: "{ground_truth_transcription}"'
    )


async def _run_mcp_meeting_transcription_test(
    meeting_url: str,
    ground_truth_transcription: str,
    duration_seconds: int = 30,
    max_wer_threshold: float = 0.1,
) -> None:
    """Executes a meeting transcription test by joining a meeting and processing audio.

    This function sets up a test environment with browser, audio capture, VAD chunking,
    and transcription components to verify the audio transcription pipeline.

    Args:
        meeting_url: URL for the meeting to join
        ground_truth_transcription: Expected text in the transcription
        duration_seconds: How long to collect transcriptions (in seconds)
        max_wer_threshold: Maximum acceptable Word Error Rate (default 0.1 or 10%)
    """
    import logging

    from fastmcp import Client

    from meeting_agent.server import mcp

    logger = logging.getLogger("meeting_agent")

    transcript_url = AnyUrl("transcript://live")
    transcription_update_count = 0

    async def _handler(message) -> None:  # noqa: ANN001
        nonlocal transcription_update_count
        logger.info("Received message: %s", message)
        if (
            isinstance(message, ServerNotification)
            and isinstance(message.root, ResourceUpdatedNotification)
            and message.root.params.uri == transcript_url
        ):
            logger.info("Transcription update received")
            transcription_update_count += 1

    client = Client(mcp, message_handler=_handler)

    async with client:
        await client.session.subscribe_resource(transcript_url)

        await client.call_tool(
            "join_meeting",
            {
                "meeting_url": meeting_url,
                "participant_name": "Test Participant",
            },
        )

        await asyncio.sleep(duration_seconds)

        transcription_resource = await client.read_resource("transcript://live")
        transcription = transcription_resource[0].text  # type: ignore[attr-defined]

    assert transcription, "No transcription received"
    assert transcription_update_count > 0, (
        "No transcription updates received. "
        f"Expected at least one update, got {transcription_update_count}"
    )

    wer = _calculate_wer(transcription, ground_truth_transcription)
    assert wer <= max_wer_threshold, (
        f"Transcription quality below threshold. WER: {wer:.2f}, "
        f"Max allowed: {max_wer_threshold:.2f}\n"
        f'Transcription: "{transcription}"\n'
        f'Ground truth: "{ground_truth_transcription}"'
    )


def _calculate_wer(
    transcription: str,
    ground_truth_transcription: str,
) -> float:
    """Calculates Word Error Rate between transcription and ground truth.

    Args:
        transcription: The transcription to compare.
        ground_truth_transcription: The expected transcription.

    Returns:
        The Word Error Rate (lower is better, 0 is perfect).
    """
    return jiwer.wer(ground_truth_transcription.lower(), transcription.lower())
