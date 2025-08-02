from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastmcp import Client
from joinly_common.types import (
    ServiceUsage,
    SpeakerRole,
    Transcript,
    TranscriptSegment,
    Usage,
)

__all__ = [
    "ServiceUsage",
    "SpeakerRole",
    "Transcript",
    "TranscriptSegment",
    "Usage",
]

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[Any]]


@dataclass
class McpClientConfig:
    """Configuration for an MCP client."""

    client: Client
    exclude: list[str] = field(default_factory=list)
