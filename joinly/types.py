from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from shared.types import SpeakerRole, Transcript, TranscriptSegment

__all__ = [
    "SpeakerRole",
    "Transcript",
    "TranscriptSegment",
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


class MeetingChatMessage(BaseModel):
    """A class to represent a chat message in a meeting.

    Attributes:
        text (str): The content of the chat message.
        timestamp (float): The timestamp of when the message was sent.
        sender (str | None): The sender of the message, if available.
    """

    text: str
    timestamp: float | None = Field(..., exclude=True)
    sender: str | None = None

    model_config = ConfigDict(frozen=True)

    @computed_field(alias="timestamp")
    @property
    def timestamp_readable(self) -> str | None:
        """Expose ISO-formatted timestamp in JSON instead of the float."""
        if self.timestamp:
            return datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat()
        return None


class MeetingChatHistory(BaseModel):
    """A class to represent the chat history of a meeting."""

    messages: list[MeetingChatMessage] = Field(default_factory=list)


class MeetingParticipant(BaseModel):
    """A class to represent a participant in a meeting.

    Attributes:
        name (str): The name of the participant.
        email (str | None): The email address of the participant.
        infos (list[str]): Additional information about the participant.
    """

    name: str
    email: str | None = None
    infos: list[str] = Field(default_factory=list)

    model_config = ConfigDict(frozen=True)
