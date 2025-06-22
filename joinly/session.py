import logging
from collections.abc import Callable, Coroutine

from joinly.core import (
    MeetingProvider,
    SpeechController,
    TranscriptionController,
)
from joinly.types import MeetingChatHistory, MeetingParticipant, Transcript

logger = logging.getLogger(__name__)


class MeetingSession:
    """Orchestrates meeting actions."""

    def __init__(
        self,
        meeting_provider: MeetingProvider,
        transcription_controller: TranscriptionController,
        speech_controller: SpeechController,
    ) -> None:
        """Initialize a meeting session.

        Args:
            meeting_provider (MeetingProvider): The meeting provider to use.
            transcription_controller (TranscriptionController): Controller for managing
                transcriptions.
            speech_controller (SpeechController): Controller for managing speech
                actions.
        """
        self._meeting_provider = meeting_provider
        self._transcription_controller = transcription_controller
        self._speech_controller = speech_controller

    @property
    def transcript(self) -> Transcript:
        """Return the current transcript of the meeting."""
        return self._transcription_controller.transcript

    @property
    def meeting_seconds(self) -> float:
        """Return the current meeting duration in seconds."""
        return self._transcription_controller.transcript_seconds

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
        self,
        meeting_url: str | None = None,
        participant_name: str | None = None,
        passcode: str | None = None,
    ) -> None:
        """Join a meeting using the provided URL.

        Args:
            meeting_url (str | None): The URL of the meeting to join. Might be required
                depending on the meeting provider.
            participant_name (str | None): The name of the participant.
                Defaults to the sessions participant name.
            passcode (str | None): The password or passcode for the meeting
                (if required).
        """
        await self._meeting_provider.join(meeting_url, participant_name, passcode)
        await self._transcription_controller.start()
        await self._speech_controller.start()

    async def leave_meeting(self, *, force: bool = False) -> None:
        """Leave the current meeting.

        Args:
            force (bool): Whether to force leave the meeting, otherwise wait for speech.
                Defaults to False.
        """
        if not force:
            await self._speech_controller.wait_until_no_speech()
        await self._meeting_provider.leave()
        await self._transcription_controller.stop()
        await self._speech_controller.stop()

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
        await self._meeting_provider.send_chat_message(message)

    async def get_chat_history(self) -> MeetingChatHistory:
        """Get the chat history from the meeting.

        Returns:
            MeetingChatHistory: The chat history of the meeting.
        """
        return await self._meeting_provider.get_chat_history()

    async def get_participants(self) -> list[MeetingParticipant]:
        """Get the list of participants in the meeting.

        Returns:
            list[MeetingParticipant]: A list of participants in the meeting.
        """
        return await self._meeting_provider.get_participants()

    async def mute(self) -> None:
        """Mute yourself in the meeting."""
        await self._meeting_provider.mute()

    async def unmute(self) -> None:
        """Unmute yourself in the meeting."""
        await self._meeting_provider.unmute()
