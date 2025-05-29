import logging
from collections.abc import Callable, Coroutine

from joinly.core import (
    MeetingController,
    SpeechController,
    TranscriptionController,
)
from joinly.types import Transcript

logger = logging.getLogger(__name__)


class MeetingSession:
    """Orchestrates meeting actions on top of controllers."""

    def __init__(
        self,
        meeting_controller: MeetingController,
        transcription_controller: TranscriptionController,
        speech_controller: SpeechController,
    ) -> None:
        """Initialize a meeting session."""
        self._meeting_controller = meeting_controller
        self._transcription_controller = transcription_controller
        self._speech_controller = speech_controller

    @property
    def transcript(self) -> Transcript:
        """Return the current transcript of the meeting."""
        return self._transcription_controller.transcript

    def add_transcription_listener(
        self, listener: Callable[[str], Coroutine[None, None, None]]
    ) -> Callable[[], None]:
        """Add a listener for transcription events.

        Args:
            listener: A callable that takes an event as argument.

        Returns:
            A callable to remove the listener.
        """
        return self._transcription_controller.add_listener(listener)

    async def join_meeting(
        self, meeting_url: str | None = None, participant_name: str | None = None
    ) -> None:
        """Join a meeting using the provided URL.

        Args:
            meeting_url (str | None): The URL of the meeting to join. Might be required
                depending on the meeting provider.
            participant_name (str | None): The name of the participant.
                Defaults to the sessions participant name.
        """
        await self._meeting_controller.join(meeting_url, participant_name)

    async def leave_meeting(self, *, force: bool = False) -> None:
        """Leave the current meeting.

        Args:
            force (bool): Whether to force leave the meeting, otherwise wait for speech.
                Defaults to False.
        """
        if not force:
            await self._speech_controller.wait_until_no_speech()
        await self._meeting_controller.leave()

    async def speak_text(self, text: str) -> None:
        """Speak the provided text using TTS.

        Args:
            text (str): The text to be spoken.
        """
        await self._speech_controller.speak_text(text)

    async def send_chat_message(self, message: str) -> None:
        """Send a chat message in the meeting.

        Args:
            message (str): The message to be sent.
        """
        await self._meeting_controller.send_chat_message(message)
