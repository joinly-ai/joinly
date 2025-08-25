import contextlib
import logging
from collections.abc import Callable, Coroutine

from joinly.core import (
    MeetingProvider,
    SpeechController,
    TranscriptionController,
    VideoReader,
)
from joinly.types import (
    MeetingChatHistory,
    MeetingParticipant,
    Transcript,
    VideoSnapshot,
)
from joinly.utils.clock import Clock
from joinly.utils.events import EventBus, EventType

logger = logging.getLogger(__name__)


class MeetingSession:
    """Orchestrates meeting actions."""

    def __init__(
        self,
        meeting_provider: MeetingProvider,
        transcription_controller: TranscriptionController,
        speech_controller: SpeechController,
        video_reader: VideoReader,
    ) -> None:
        """Initialize a meeting session.

        Args:
            meeting_provider (MeetingProvider): The meeting provider to use.
            transcription_controller (TranscriptionController): Controller for managing
                transcriptions.
            speech_controller (SpeechController): Controller for managing speech
                actions.
            video_reader (VideoReader): Controller for managing video actions.
        """
        self._meeting_provider = meeting_provider
        self._transcription_controller = transcription_controller
        self._speech_controller = speech_controller
        self._video_reader = video_reader
        self._clock: Clock | None = None
        self._transcript: Transcript | None = None
        self._event_bus = EventBus()

    @property
    def transcript(self) -> Transcript:
        """Return the current transcript of the meeting."""
        if self._transcript is None:
            msg = "Not joined any meeting, cannot access transcript."
            raise RuntimeError(msg)
        return self._transcript

    @property
    def meeting_seconds(self) -> float:
        """Return the current meeting duration in seconds."""
        if self._clock is None:
            msg = "Not joined any meeting, cannot access meeting duration."
            raise RuntimeError(msg)
        return self._clock.now_s

    def subscribe(
        self, event_type: EventType, handler: Callable[[], Coroutine[None, None, None]]
    ) -> Callable[[], None]:
        """Add a listener for transcription events.

        Args:
            event_type (EventType): The type of event to listen for.
            handler: A callable.

        Returns:
            A callable to remove the handler.
        """
        return self._event_bus.subscribe(event_type, handler)

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
        self._clock = Clock()
        self._transcript = Transcript()

        _unsubscribe: Callable[[], None] | None = None

        async def unmute_on_start() -> None:
            """Unmute the participant when the meeting starts."""
            if _unsubscribe is not None:
                _unsubscribe()
            with contextlib.suppress(Exception):
                await self._meeting_provider.unmute()

        _unsubscribe = self._event_bus.subscribe("segment", unmute_on_start)

        await self._transcription_controller.start(
            self._clock, self._transcript, self._event_bus
        )
        await self._speech_controller.start(
            self._clock, self._transcript, self._event_bus
        )

    async def leave_meeting(self) -> None:
        """Leave the current meeting."""
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

    async def get_video_snapshot(self) -> VideoSnapshot:
        """Get a snapshot of the current video feed.

        Returns:
            VideoSnapshot: The current video snapshot.
        """
        return await self._video_reader.snapshot()

    async def mute(self) -> None:
        """Mute yourself in the meeting."""
        await self._meeting_provider.mute()

    async def unmute(self) -> None:
        """Unmute yourself in the meeting."""
        await self._meeting_provider.unmute()
