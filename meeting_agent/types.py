from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """A class to represent a segment of a transcript."""

    text: str
    start: float
    end: float
    speaker: str | None = None


class Transcript(BaseModel):
    """A class to represent a transcript."""

    segments: list[TranscriptSegment] = Field(default_factory=list)

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
