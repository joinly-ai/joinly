from typing import Any

from tests.utils.meeting_transcription import run_meeting_transcription_test


async def test_meeting_transcription_mockup(meeting_mockup: dict[str, Any]) -> None:
    """Test transcription with meeting mockup."""
    await run_meeting_transcription_test(
        meeting_url=meeting_mockup["url"],
        ground_truth_transcription=meeting_mockup["transcription"],
        duration_seconds=meeting_mockup["duration"],
    )
