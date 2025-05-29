from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, PrivateAttr, computed_field


class ProviderNotSupportedError(Exception):
    """Raised when a provider does not support a requested feature."""


class SpeechInterruptedError(Exception):
    """Raised when speech is interrupted by detected speech."""


@dataclass
class VADWindow:
    """A class to represent an audio window with vad."""

    pcm: bytes
    start: float
    is_speech: bool


@dataclass
class SpeechSegment:
    """A class to represent synthesized speech."""

    text: str
    pcm: bytes


class TranscriptSegment(BaseModel):
    """A class to represent a segment of a transcript."""

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
        """The segments of the transcript sorted by start time."""
        return sorted(self._segments, key=lambda s: s.start)

    @property
    def text(self) -> str:
        """Return the full text of the transcript."""
        return " ".join([segment.text for segment in self.segments])

    @property
    def speakers(self) -> set[str]:
        """Return a set of unique speakers in the transcript."""
        return {
            segment.speaker for segment in self.segments if segment.speaker is not None
        }
