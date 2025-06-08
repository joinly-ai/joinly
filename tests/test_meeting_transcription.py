import asyncio
from typing import Any

import jiwer
from mcp import ResourceUpdatedNotification, ServerNotification
from pydantic import AnyUrl

from joinly.session import MeetingSession
from joinly.types import Transcript


async def test_meeting_transcription_mockup(
    mockup_browser_meeting: dict[str, Any], meeting_session: MeetingSession
) -> None:
    """Test transcription with mockup browser meeting."""
    await _run_meeting_transcription_test(
        meeting_session=meeting_session,
        meeting_url=mockup_browser_meeting["url"],
        ground_truth_transcription=mockup_browser_meeting["transcription"],
        duration_seconds=mockup_browser_meeting["duration"] + 5,
    )


async def test_mcp_meeting_transcription_mockup(
    mockup_browser_meeting: dict[str, Any],
) -> None:
    """Test transcription with mockup browser meeting."""
    await _run_mcp_meeting_transcription_test(
        meeting_url=mockup_browser_meeting["url"],
        ground_truth_transcription=mockup_browser_meeting["transcription"],
        duration_seconds=mockup_browser_meeting["duration"] + 5,
    )


async def _run_meeting_transcription_test(
    meeting_session: MeetingSession,
    meeting_url: str,
    ground_truth_transcription: str,
    duration_seconds: int = 30,
    max_wer_threshold: float = 0.2,
) -> None:
    """Executes a meeting transcription test by joining a meeting and processing audio.

    This function sets up a test environment with browser, audio capture, VAD chunking,
    and transcription components to verify the audio transcription pipeline.

    Args:
        meeting_session: The MeetingSession instance to use for the test
        meeting_url: URL for the meeting to join
        ground_truth_transcription: Expected text in the transcription
        duration_seconds: How long to collect transcriptions (in seconds)
        max_wer_threshold: Maximum acceptable Word Error Rate (default 0.2 or 20%)
    """
    await meeting_session.join_meeting(
        meeting_url=meeting_url,
        participant_name="Test Participant",
    )
    await asyncio.sleep(duration_seconds)

    ms_transcription = meeting_session.transcript.text
    assert ms_transcription, "No transcription received"

    wer = _calculate_wer(ms_transcription, ground_truth_transcription)
    assert wer <= max_wer_threshold, (
        f"Transcription quality below threshold. WER: {wer:.2f}, "
        f"Max allowed: {max_wer_threshold:.2f}\n"
        f'Transcription: "{ms_transcription}"\n'
        f'Ground truth: "{ground_truth_transcription}"'
    )


async def _run_mcp_meeting_transcription_test(
    meeting_url: str,
    ground_truth_transcription: str,
    duration_seconds: int = 30,
    max_wer_threshold: float = 0.2,
) -> None:
    """Executes a meeting transcription test by joining a meeting and processing audio.

    This function sets up a test environment with browser, audio capture, VAD chunking,
    and transcription components to verify the audio transcription pipeline.

    Args:
        meeting_url: URL for the meeting to join
        ground_truth_transcription: Expected text in the transcription
        duration_seconds: How long to collect transcriptions (in seconds)
        max_wer_threshold: Maximum acceptable Word Error Rate (default 0.2 or 20%)
    """
    from fastmcp import Client

    from joinly.server import mcp

    transcript_url = AnyUrl("transcript://live")
    transcription_update_count = 0

    async def _handler(message) -> None:  # noqa: ANN001
        nonlocal transcription_update_count
        if (
            isinstance(message, ServerNotification)
            and isinstance(message.root, ResourceUpdatedNotification)
            and message.root.params.uri == transcript_url
        ):
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

        transcript_resource = await client.read_resource("transcript://live")
        transcript = Transcript.model_validate_json(transcript_resource[0].text)  # type: ignore[attr-defined]

    assert transcript, "No transcription received"
    assert transcription_update_count > 0, (
        "No transcription updates received. "
        f"Expected at least one update, got {transcription_update_count}"
    )

    wer = _calculate_wer(transcript.text, ground_truth_transcription)
    assert wer <= max_wer_threshold, (
        f"Transcription quality below threshold. WER: {wer:.2f}, "
        f"Max allowed: {max_wer_threshold:.2f}\n"
        f'Transcription: "{transcript.text}"\n'
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
