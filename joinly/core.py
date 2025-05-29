import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Protocol

from joinly.types import (
    SpeechSegment,
    Transcript,
    TranscriptSegment,
    VADWindow,
)


class AudioStream(Protocol):
    """Common audio-stream properties.

    Attributes:
        sample_rate (int): The sample rate of the audio stream in Hz.
        byte_depth (int): The byte depth of the audio stream in bytes.
        chunk_size (int): The size of audio chunks in bytes.
    """

    sample_rate: int
    byte_depth: int
    chunk_size: int


class AudioReader(AudioStream, Protocol):
    """Protocol for audio stream sources.

    Defines the interface for objects that provide audio data.
    """

    async def read(self) -> bytes:
        """Read a chunk of audio data.

        Returns:
            bytes: A chunk of raw PCM audio data.
        """
        ...


class AudioWriter(AudioStream, Protocol):
    """Protocol for audio output destinations.

    Defines the interface for objects that consume audio data.
    """

    async def write(self, pcm: bytes) -> None:
        """Write audio data to the sink.

        Args:
            pcm: Raw PCM audio data.
        """
        ...


class VAD(Protocol):
    """Protocol for Voice Activity Detection.

    Defines the interface for detecting speech in audio streams.
    """

    def stream(self, reader: AudioReader) -> AsyncIterator[VADWindow]:
        """Extract windows containing speech from an audio source.

        Args:
            reader: The audio reader to process.

        Returns:
            AsyncIterator[VADWindow]: Stream of audio windows containing vad
                information.
        """
        ...


class STT(Protocol):
    """Protocol for speech-to-text transcription.

    Defines the interface for streaming and finalizing transcriptions.
    """

    def stream(
        self, windows: AsyncIterator[VADWindow]
    ) -> AsyncIterator[TranscriptSegment]:
        """Transcribe an utterance into text segments.

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
    """

    def stream(self, text: str) -> AsyncIterator[SpeechSegment]:
        """Convert text to synthesized speech.

        Args:
            text: The text to synthesize.

        Returns:
            AsyncIterator[SpeechSegment]: Stream of speech segments with audio and text.
        """
        ...


class MeetingController(Protocol):
    """Protocol for controlling meeting interactions.

    Defines the interface for joining, interacting with, and leaving meetings.
    """

    async def join(self, url: str | None = None, name: str | None = None) -> None:
        """Join a meeting.

        Args:
            url: The meeting URL to join.
            name: The name to use in the meeting.
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


class TranscriptionController(Protocol):
    """Protocol for controlling transcription processes.

    Defines the interface for starting and stopping transcriptions.
    """

    @property
    def transcript(self) -> Transcript:
        """Get the current transcript.

        Returns:
            Transcript: The current transcript of the audio processed.
        """
        ...

    @property
    def no_speech_event(self) -> asyncio.Event:
        """Get the event indicating no speech detected.

        Returns:
            asyncio.Event: An event that is set when no speech is detected.
        """
        ...

    def add_listener(
        self, listener: Callable[[str], Coroutine[None, None, None]]
    ) -> Callable[[], None]:
        """Add a listener for transcript updates.

        Args:
            listener: A callable that takes an event string and returns a coroutine.

        Returns:
            Callable[[], None]: A function to remove the listener.
        """
        ...


class SpeechController(Protocol):
    """Protocol for controlling speech output.

    Defines the interface for speaking text aloud.
    """

    async def speak_text(self, text: str) -> None:
        """Speak the provided text.

        Args:
            text: The text to speak.
        """
        ...

    async def wait_until_no_speech(self) -> None:
        """Wait until no speech is emitted."""
        ...


class MeetingProvider(Protocol):
    """Protocol defining the interface for meeting providers.

    A provider must implement audio input/output capabilities and meeting control
    functionality. This protocol ensures all providers have a consistent interface.

    Attributes:
        meeting_controller (MeetingController): The controller for managing meetings.
        audio_reader (AudioReader): The audio input source for the provider.
        audio_writer (AudioWriter): The audio output destination for the provider.
    """

    meeting_controller: MeetingController
    audio_reader: AudioReader
    audio_writer: AudioWriter
