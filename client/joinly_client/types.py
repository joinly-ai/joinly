from collections.abc import Awaitable, Callable
from typing import Any

from shared.types import SpeakerRole, Transcript, TranscriptSegment

__all__ = [
    "SpeakerRole",
    "Transcript",
    "TranscriptSegment",
]

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[Any]]
