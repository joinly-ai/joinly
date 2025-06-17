from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, computed_field


class ProviderNotSupportedError(Exception):
    """Raised when a provider does not support a requested feature."""


class IncompatibleAudioFormatError(Exception):
    """Raised when an audio format is incompatible with the expected or given format."""


class SpeechInterruptedError(Exception):
    """Raised when speech is interrupted by detected speech."""


@dataclass
class AudioFormat:
    """Properties of pcm audio.

    Attributes:
        sample_rate (int): The sample rate of the audio stream in Hz.
        byte_depth (int): The byte depth of the audio stream in bytes.
    """

    sample_rate: int
    byte_depth: int


@dataclass
class SpeechWindow:
    """A class to represent an audio window with voice activity detection.

    Attributes:
        data (bytes): The raw PCM audio data for the window.
        start (float): The start time of the window in seconds.
        is_speech (bool): Whether the window contains speech.
    """

    data: bytes
    start: float
    is_speech: bool


class TranscriptSegment(BaseModel):
    """A class to represent a segment of a transcript.

    Attributes:
        text (str): The text of the segment.
        start (float): The start time of the segment in seconds.
        end (float): The end time of the segment in seconds.
        speaker (str | None): The speaker of the segment, if available.
    """

    text: str
    start: float
    end: float
    speaker: str | None = None

    model_config = ConfigDict(frozen=True)


class Transcript(BaseModel):
    """A class to represent a transcript."""

    _segments: set[TranscriptSegment] = PrivateAttr(default_factory=set)

    def add_segment(self, segment: TranscriptSegment) -> None:
        """Add a segment to the transcript.

        Args:
            segment (TranscriptSegment): The segment to add.
        """
        self._segments.add(segment)

    def __init__(
        self,
        *,
        segments: Iterable[TranscriptSegment | dict] | None = None,
        **data,  # noqa: ANN003
    ) -> None:
        """Initialize a transcript with optional segments.

        Args:
            segments: An iterable of TranscriptSegment objects or dictionaries that
                can be converted to TranscriptSegment.
            **data: Additional data to pass to the parent class.
        """
        super().__init__(**data)
        if segments:
            for s in segments:
                segment = (
                    s
                    if isinstance(s, TranscriptSegment)
                    else TranscriptSegment.model_validate(s)
                )
                self._segments.add(segment)

    @computed_field
    @property
    def segments(self) -> list[TranscriptSegment]:
        """The segments of the transcript sorted by start time.

        Returns:
            list[TranscriptSegment]: A sorted list of TranscriptSegment objects.
        """
        return sorted(self._segments, key=lambda s: s.start)

    @property
    def text(self) -> str:
        """Return the full text of the transcript.

        Returns:
            str: The concatenated text of all segments in the transcript.
        """
        return " ".join([segment.text for segment in self.segments])

    @property
    def speakers(self) -> set[str]:
        """Return a set of unique speakers in the transcript.

        Returns:
            set[str]: A set of unique speaker identifiers.
        """
        return {
            segment.speaker for segment in self.segments if segment.speaker is not None
        }


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
