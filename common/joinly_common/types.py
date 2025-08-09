from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    RootModel,
    computed_field,
    field_validator,
)


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
        role (SpeakerRole): The role of the speaker in the segment.
    """

    text: str
    start: float
    end: float
    speaker: str | None = None
    role: SpeakerRole = Field(default=SpeakerRole.participant)

    model_config = ConfigDict(frozen=True)

    @field_validator("start", "end", mode="after")
    @classmethod
    def _round(cls, v: float) -> float:
        """Round the start and end times to 3 decimal places."""
        return float(Decimal(str(v)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


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
        timestamp (str | None): The timestamp of when the message was sent.
        sender (str | None): The sender of the message, if available.
    """

    text: str
    timestamp: str | None = None
    sender: str | None = None

    model_config = ConfigDict(frozen=True)


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


class MeetingParticipantList(RootModel):
    """A class to represent a list of participants in a meeting.

    Attributes:
        root (list[MeetingParticipant]): A list of MeetingParticipant objects.
    """

    root: list[MeetingParticipant] = Field(default_factory=list)


class ServiceUsage(BaseModel):
    """Dataclass to hold usage statistics for a service."""

    usage: dict[str, int | float]
    meta: dict[str, str | int | float] = Field(default_factory=dict)

    def add(self, usage: "ServiceUsage") -> None:
        """Add usage statistics from another ServiceUsage instance.

        Args:
            usage: Another ServiceUsage instance containing usage statistics to add.
        """
        for key, value in usage.usage.items():
            self.usage[key] = self.usage.get(key, 0) + value
        for key, value in usage.meta.items():
            self.meta[key] = value

    def __str__(self) -> str:
        """Return a string representation of the ServiceUsage instance."""
        usage_str = ", ".join(
            f"{(v if isinstance(v, int) else f'{v:.4f}')} {k.replace('_', ' ')}"
            for k, v in self.usage.items()
        )
        meta_str = ", ".join(f"{k}={v}" for k, v in self.meta.items())
        return f"{usage_str} [{meta_str}]"


class Usage(RootModel):
    """Dataclass to hold the overall usage statistics."""

    root: dict[str, ServiceUsage] = Field(default_factory=dict)

    def add(
        self,
        service: str,
        usage: ServiceUsage | dict[str, int | float],
        meta: dict[str, str | int | float] | None = None,
    ) -> None:
        """Add usage statistics for a specific service.

        Args:
            service: The name of the service.
            usage: A ServiceUsage instance or a dictionary containing usage statistics.
            meta: Optional metadata associated with the usage statistics.
        """
        service_usage = (
            ServiceUsage(usage=usage, meta=meta or {})
            if isinstance(usage, dict)
            else usage
        )
        if service not in self.root:
            self.root[service] = service_usage
        else:
            self.root[service].add(service_usage)

    def merge(self, other: "Usage") -> "Usage":
        """Merge another Usage instance into this one, creating a copy.

        Args:
            other: Another Usage instance to merge.

        Returns:
            Usage: A new Usage instance containing the merged statistics.
        """
        merged = Usage()
        for service, usage in self.root.items():
            merged.add(service, usage)
        for service, usage in other.root.items():
            merged.add(service, usage)
        return merged

    def __str__(self) -> str:
        """Return a string representation of the Usage instance."""
        return "\n".join(f"{service}: {usage}" for service, usage in self.root.items())
