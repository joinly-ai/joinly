import json
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any

import pytest

from joinly.container import SessionContainer
from joinly.providers.browser.meeting_provider import PLATFORMS
from joinly.session import MeetingSession
from tests.utils.mockup_browser_controller import MockupBrowserPlatformController
from tests.utils.mockup_browser_meeting import serve_mockup_browser_meeting


def speech_audio_samples() -> list[dict[str, Any]]:
    """Returns a list of speech audio samples for testing.

    Returns:
        A list of dictionaries containing speech audio sample data.
    """
    data_path = Path(__file__).parent / "data" / "speech_audio"
    samples = json.loads((data_path / "test_samples.json").read_text(encoding="utf-8"))
    for sample in samples:
        sample["filepath"] = data_path / sample["filename"]

    return samples


@pytest.fixture(params=speech_audio_samples(), scope="session")
async def mockup_browser_meeting(
    request: pytest.FixtureRequest,
) -> AsyncGenerator[dict[str, Any], None]:
    """Fixture to set up a mockup browser meeting for testing."""
    audio_sample_info = request.param
    async with serve_mockup_browser_meeting(audio_sample_info["filepath"]) as url:
        yield {
            "url": url,
            "transcription": audio_sample_info["transcription"],
            "duration": audio_sample_info["duration"],
        }


@pytest.fixture(autouse=True)
def _inject_mockup_browser_controller(
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    """Injects the MockupBrowserPlatformController if the fixture is requested."""
    if "mockup_browser_meeting" in request.fixturenames:
        PLATFORMS.insert(0, MockupBrowserPlatformController)
        yield
        PLATFORMS.remove(MockupBrowserPlatformController)
    else:
        yield


@pytest.fixture
async def meeting_session() -> AsyncGenerator[MeetingSession, None]:
    """Fixture to set up a meeting session for testing."""
    session_container = SessionContainer()

    meeting_session = await session_container.__aenter__()
    try:
        yield meeting_session
    finally:
        await session_container.__aexit__()
