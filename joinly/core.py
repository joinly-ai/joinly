import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Protocol

from joinly.types import (
    AudioFormat,
    SpeechWindow,
    Transcript,
    TranscriptSegment,
)


class AudioReader(Protocol):
    """Protocol for audio stream sources.

    Defines the interface for objects that provide audio data.

    Attributes:
        format (AudioFormat): The format of the audio data being read.
    """

    format: AudioFormat

    async def read(self) -> bytes:
        """Read a chunk of audio data.

        Returns:
            bytes: A chunk of raw PCM audio data.
        """
        ...


class AudioWriter(Protocol):
    """Protocol for audio output destinations.

    Defines the interface for objects that consume audio data.

    Attributes:
        format (AudioFormat): The format of the audio data being written.
        chunk_size (int): The smallest accepted size of an audio chunk in bytes.
    """

    format: AudioFormat
    chunk_size: int

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

    def stream(self, reader: AudioReader) -> AsyncIterator[SpeechWindow]:
        """Extract windows containing speech from an audio source.

        The audio included in SpeechWindow must be in the same format as
        the AudioReader's format.

        Args:
            reader: The audio reader to process.

        Returns:
            AsyncIterator[SpeechWindow]: Stream of audio windows containing speech
                information.

        Raises:
            IncompatibleAudioFormatError: If the audio format of the reader is
                incompatible with the expected format.
        """
        ...


class STT(Protocol):
    """Protocol for speech-to-text transcription.

    Defines the interface for streaming and finalizing transcriptions.
    """

    def stream(
        self, windows: AsyncIterator[SpeechWindow], audio_format: AudioFormat
    ) -> AsyncIterator[TranscriptSegment]:
        """Transcribe an utterance into text segments.

        If the audio format is not supported, an exception should be raised.

        Args:
            windows: An asynchronous iterator of audio windows to transcribe.
            audio_format: The format of the audio windows.

        Returns:
            AsyncIterator[TranscriptSegment]: Stream of transcript segments with text
                and timing.

        Raises:
            IncompatibleAudioFormatError: If the audio format is incompatible
                with the expected format.
        """
        ...


class TTS(Protocol):
    """Protocol for text-to-speech synthesis.

    Defines the interface for converting text to audio.
    """

    def stream(self, text: str, audio_format: AudioFormat) -> AsyncIterator[bytes]:
        """Convert text to synthesized speech.

        The audio data yielded must be in the specified format. If the audio format
        is not supported, an exception should be raised.

        Args:
            text: The text to synthesize.
            audio_format: The format of the audio to be generated.

        Returns:
            AsyncIterator[bytes]: Stream of raw PCM audio data in the specified format.

        Raises:
            IncompatibleAudioFormatError: If the audio format is incompatible
                with the expected format.
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

    Attributes:
        reader (AudioReader): The audio reader to use for transcription.
        vad (VAD): The voice activity detection service to use.
        stt (STT): The speech-to-text service to use for transcription.
    """

    reader: AudioReader
    vad: VAD
    stt: STT

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

    async def start(self) -> None:
        """Start the transcription process."""
        ...

    async def stop(self) -> None:
        """Stop the transcription process."""
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

    async def start(self) -> None:
        """Start the speech output process."""
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

    async def wait_until_no_speech(self) -> None:
        """Wait until no speech is emitted."""
        ...
