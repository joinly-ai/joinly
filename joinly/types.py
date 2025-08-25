from dataclasses import dataclass
from typing import Literal

from joinly_common.types import (
    MeetingChatHistory,
    MeetingChatMessage,
    MeetingParticipant,
    MeetingParticipantList,
    ServiceUsage,
    SpeakerRole,
    Transcript,
    TranscriptSegment,
    Usage,
)

__all__ = [
    "MeetingChatHistory",
    "MeetingChatMessage",
    "MeetingParticipant",
    "MeetingParticipantList",
    "ServiceUsage",
    "SpeakerRole",
    "Transcript",
    "TranscriptSegment",
    "Usage",
]


class ProviderNotSupportedError(Exception):
    """Raised when a provider does not support a requested feature."""


class IncompatibleAudioFormatError(Exception):
    """Raised when an audio format is incompatible with the expected or given format."""


class SpeechInterruptedError(Exception):
    """Raised when speech is interrupted by detected speech."""

    _TEMPLATE = 'Interrupted by detected speech. Spoken until now: "%s..."'

    def __init__(self, spoken_text: str = "") -> None:
        """Initialize the SpeechInterruptedError with the spoken text."""
        self.spoken_text: str = spoken_text
        super().__init__(self.__str__())

    def __str__(self) -> str:
        """Return a string representation of the error."""
        return self._TEMPLATE % self.spoken_text


@dataclass(frozen=True, slots=True)
class AudioFormat:
    """Properties of pcm audio.

    Attributes:
        sample_rate (int): The sample rate of the audio stream in Hz.
        byte_depth (int): The byte depth of the audio stream in bytes.
    """

    sample_rate: int
    byte_depth: int


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """A class to represent a chunk of audio data.

    Attributes:
        data (bytes): The raw PCM audio data.
        time_ns (int): The timestamp of the audio chunk in nanoseconds.
        speaker (str | None): The (main) speaker of the audio chunk, if available.
    """

    data: bytes
    time_ns: int
    speaker: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechWindow:
    """A class to represent an audio window with voice activity detection.

    Attributes:
        data (bytes): The raw PCM audio data for the window.
        time_ns (int): The timestamp of the audio window in nanoseconds.
        is_speech (bool): Whether the window contains speech.
        speaker (str | None): The speaker of the audio window, if available.
    """

    data: bytes
    time_ns: int
    is_speech: bool
    speaker: str | None = None


@dataclass(frozen=True, slots=True)
class VideoSnapshot:
    """A class to represent a snapshot of video data.

    Attributes:
        data (bytes): The raw video data.
        media_type (Literal["image/png"]): The media type of the video snapshot.
    """

    data: bytes
    media_type: Literal["image/png", "image/jpeg"] = "image/png"
