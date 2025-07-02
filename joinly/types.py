from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, computed_field


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


class SpeakerRole(str, Enum):
    """An enumeration of speaker roles in a meeting.

    Attributes:
        participant (str): Represents a (normal) participant in the meeting.
        assistant (str): Represents this assistant in the meeting.
    """

    participant = "participant"
    assistant = "assistant"


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
    role: SpeakerRole = Field(default=SpeakerRole.participant, exclude=True)

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

    def after(self, seconds: float) -> "Transcript":
        """Return a transcript copy containing the segments after the given seconds."""
        filtered = [s for s in self.segments if s.start > seconds]
        return Transcript(segments=filtered)

    def before(self, seconds: float) -> "Transcript":
        """Return a transcript copy containing the segments before the given seconds."""
        filtered = [s for s in self.segments if s.end < seconds]
        return Transcript(segments=filtered)

    def with_role(self, role: SpeakerRole) -> "Transcript":
        """Return a transcript copy containing segments with the specified role."""
        filtered = [s for s in self.segments if s.role == role]
        return Transcript(segments=filtered)

    def compact(self, max_gap: float = 0.5) -> "Transcript":
        """Return a compacted copy of the transcript.

        Segments with the same speaker and role that are within the specified gap
        are merged into a single segment.

        Args:
            max_gap (float): The maximum gap in seconds between segments to be merged.

        Returns:
            Transcript: A new Transcript object with compacted segments.
        """
        compacted: list[TranscriptSegment] = []

        for segment in self.segments:
            if (
                compacted
                and compacted[-1].speaker == segment.speaker
                and compacted[-1].role == segment.role
                and segment.start - compacted[-1].end <= max_gap
            ):
                last_segment = compacted[-1]
                compacted[-1] = TranscriptSegment(
                    text=last_segment.text + " " + segment.text,
                    start=last_segment.start,
                    end=segment.end,
                    speaker=last_segment.speaker,
                    role=last_segment.role,
                )
            else:
                compacted.append(segment)

        return Transcript(segments=compacted)


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
