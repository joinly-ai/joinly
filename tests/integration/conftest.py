import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest

from tests.utils.meeting_mockup import serve_meeting_mockup


def speech_audio_samples() -> list[dict[str, Any]]:
    """Returns a list of speech audio samples for testing.

    Returns:
        A list of dictionaries containing speech audio sample data.
    """
    data_path = Path(__file__).parent.parent / "data" / "speech_audio"
    samples = json.loads((data_path / "test_samples.json").read_text(encoding="utf-8"))
    for sample in samples:
        sample["filepath"] = data_path / sample["filename"]

    return samples


@pytest.fixture(params=speech_audio_samples(), scope="session")
async def meeting_mockup(
    request: pytest.FixtureRequest,
) -> AsyncGenerator[dict[str, Any], None]:
    """Fixture to set up a meeting mockup for testing."""
    audio_sample_info = request.param
    async with serve_meeting_mockup(audio_sample_info["filepath"]) as url:
        yield {
            "url": url,
            "transcription": audio_sample_info["transcription"],
            "duration": audio_sample_info["duration"],
        }
