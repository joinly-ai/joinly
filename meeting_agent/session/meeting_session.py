import asyncio
import logging
from contextlib import AsyncExitStack

from meeting_agent.browser.meeting_browser import MeetingBrowser
from meeting_agent.capture.audio_capturer import AudioCapturer
from meeting_agent.transcription.audio_transcriber import AudioTranscriber
from meeting_agent.transcription.vad_chunker import VADChunker

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


class MeetingSession:
    """A class to represent a meeting session."""

    def __init__(self, meeting_url: str, participant_name: str) -> None:
        """Initialize a meeting session.

        Args:
            meeting_url: The URL of the meeting to join.
            participant_name: The name of the participant to display in the meeting.
        """
        self._meeting_url = meeting_url
        self._participant_name = participant_name

    async def run(self) -> None:
        """Run the meeting session.

        TODO: fix the closing
        """
        audio_capturer = AudioCapturer()
        meeting_browser = MeetingBrowser(
            meeting_url=self._meeting_url,
            participant_name=self._participant_name,
            audio_sink_name=audio_capturer.sink_name,
        )
        vad_chunker = VADChunker(audio_capturer)
        audio_transcriber = AudioTranscriber(vad_chunker)

        services = [
            audio_capturer,
            meeting_browser,
            vad_chunker,
            audio_transcriber,
        ]

        try:
            async with AsyncExitStack() as stack:
                await asyncio.gather(
                    *(stack.enter_async_context(svc) for svc in services)
                )

                await meeting_browser.join()

                async for text in audio_transcriber:
                    logger.info(text)

        except asyncio.CancelledError:
            await meeting_browser.leave()
            raise
