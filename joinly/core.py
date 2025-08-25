import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

from joinly.types import (
    AudioChunk,
    AudioFormat,
    MeetingChatHistory,
    MeetingParticipant,
    SpeechWindow,
    Transcript,
    TranscriptSegment,
    VideoSnapshot,
)
from joinly.utils.clock import Clock
from joinly.utils.events import EventBus


class AudioReader(Protocol):
    """Protocol for audio stream sources.

    Defines the interface for objects that provide audio data.

    Attributes:
        audio_format (AudioFormat): The format of the audio data being read.
    """

    audio_format: AudioFormat

    async def read(self) -> AudioChunk:
        """Read a chunk of audio data.

        Returns:
            AudioChunk: A chunk of audio data.
        """
        ...


class AudioWriter(Protocol):
    """Protocol for audio output destinations.

    Defines the interface for objects that consume audio data.

    Attributes:
        audio_format (AudioFormat): The format of the audio data being written.
        chunk_size (int): The smallest accepted size of an audio chunk in bytes.
    """

    audio_format: AudioFormat
    chunk_size: int

    async def write(self, data: bytes) -> None:
        """Write audio data to the sink.

        Args:
            data: Raw PCM audio data.
        """
        ...


class VideoReader(Protocol):
    """Protocol for video stream sources.

    Defines the interface for objects that provide video data.
    """

    async def snapshot(self) -> VideoSnapshot:
        """Capture a snapshot of the current video frame.

        Returns:
            VideoSnapshot: A snapshot of the current video frame.
        """
        ...


class VAD(Protocol):
    """Protocol for Voice Activity Detection.

    Defines the interface for detecting speech in audio streams.

    Attributes:
        audio_format (AudioFormat): The expected format of the audio data for
            VAD processing.
    """

    audio_format: AudioFormat

    def stream(self, chunks: AsyncIterator[AudioChunk]) -> AsyncIterator[SpeechWindow]:
        """Stream voice activity detection results on audio windows.

        Args:
            chunks: An asynchronous iterator providing audio chunks.

        Returns:
            AsyncIterator[SpeechWindow]: Stream of audio windows containing speech
                information.
        """
        ...


class STT(Protocol):
    """Protocol for speech-to-text transcription.

    Defines the interface for streaming and finalizing transcriptions.

    Attributes:
        audio_format (AudioFormat): The format of the audio data expected for
            transcription.
    """

    audio_format: AudioFormat

    def stream(
        self, windows: AsyncIterator[SpeechWindow]
    ) -> AsyncIterator[TranscriptSegment]:
        """Transcribe an utterance into text segments.

        If the audio format is not supported, an exception should be raised.

        Args:
            windows: An asynchronous iterator of audio windows to transcribe.

        Returns:
            AsyncIterator[TranscriptSegment]: Stream of transcript segments with text
                and timing.
        """
        ...


class TTS(Protocol):
    """Protocol for text-to-speech synthesis.

    Defines the interface for converting text to audio.

    Attributes:
        audio_format (AudioFormat): The format of the audio data produced by the TTS.
    """

    audio_format: AudioFormat

    def stream(self, text: str) -> AsyncIterator[bytes]:
        """Convert text to synthesized speech.

        Args:
            text: The text to synthesize.

        Returns:
            AsyncIterator[bytes]: Stream of raw PCM audio data in the specified format.
        """
        ...


class MeetingProvider(Protocol):
    """Protocol defining the interface for meeting providers.

    A provider must implement audio input/output capabilities and meeting control
    functionality. This protocol ensures all providers have a consistent interface.
    """

    @property
    def audio_reader(self) -> AudioReader:
        """Get the audio reader for the provider.

        Returns:
            AudioReader: The audio input source.
        """
        ...

    @property
    def audio_writer(self) -> AudioWriter:
        """Get the audio writer for the provider.

        Returns:
            AudioWriter: The audio output destination.
        """
        ...

    @property
    def video_reader(self) -> VideoReader:
        """Get the video reader for the provider.

        Returns:
            VideoReader: The video input source.
        """
        ...

    async def join(
        self,
        url: str | None = None,
        name: str | None = None,
        passcode: str | None = None,
    ) -> None:
        """Join a meeting.

        Args:
            url: The meeting URL to join.
            name: The name to use in the meeting.
            passcode: The meeting password or passcode.
        """
        ...

    async def leave(self) -> None:
        """Leave the current meeting."""
        ...

    async def send_chat_message(self, message: str) -> None:
        """Send a chat message to the meeting.

        Args:
            message: The message to send.
        """
        ...

    async def get_chat_history(self) -> MeetingChatHistory:
        """Get the chat message history from the meeting.

        Returns:
            MeetingChatHistory: The chat history of the meeting.
        """
        ...

    async def get_participants(self) -> list[MeetingParticipant]:
        """Get the list of participants in the meeting.

        Returns:
            list[MeetingParticipant]: A list of participants in the meeting.
        """
        ...

    async def mute(self) -> None:
        """Mute yourself in the meeting."""
        ...

    async def unmute(self) -> None:
        """Unmute yourself in the meeting."""
        ...


class TranscriptionController(Protocol):
    """Protocol for controlling transcription processes.

    Defines the interface for starting and stopping transcriptions.

    Attributes:
        reader (AudioReader): The audio reader to use for transcription.
        vad (VAD): The voice activity detection service to use.
        stt (STT): The speech-to-text service to use for transcription.
    """

    reader: AudioReader
    vad: VAD
    stt: STT

    @property
    def no_speech_event(self) -> asyncio.Event:
        """Get the event indicating no speech detected.

        Returns:
            asyncio.Event: An event that is set when no speech is detected.
        """
        ...

    async def start(
        self, clock: Clock, transcript: Transcript, event_bus: EventBus
    ) -> None:
        """Start the transcription process.

        Args:
            clock: The clock to use for timing.
            transcript: The transcript object to which the transcription will be added.
            event_bus: The event bus to publish events to.
        """
        ...

    async def stop(self) -> None:
        """Stop the transcription process."""
        ...


class SpeechController(Protocol):
    """Protocol for controlling speech output.

    Defines the interface for speaking text.

    Attributes:
        writer (AudioWriter): The audio writer to use for output.
        tts (TTS): The text-to-speech service to use for generating speech.
        no_speech_event (asyncio.Event): An event that is set when no speech is
            detected.
    """

    writer: AudioWriter
    tts: TTS
    no_speech_event: asyncio.Event

    async def start(
        self, clock: Clock, transcript: Transcript, event_bus: EventBus
    ) -> None:
        """Start the speech output process.

        Args:
            clock: The clock to use for timing.
            transcript: The transcript object to which the speech will be added.
            event_bus: The event bus to publish events to.
        """
        ...

    async def stop(self) -> None:
        """Stop the speech output process."""
        ...

    async def speak_text(self, text: str) -> None:
        """Speak the provided text.

        Args:
            text: The text to speak.

        Raises:
            SpeechInterruptedError: If the speech is interrupted before completion.
        """
        ...
