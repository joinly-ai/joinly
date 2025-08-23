from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastmcp import Client
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
from mcp.types import CallToolResult

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

type ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[Any]]


@dataclass
class McpClientConfig:
    """Configuration for an MCP client."""

    client: Client
    exclude: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    post_callback: (
        Callable[[str, dict[str, Any], CallToolResult], Awaitable[CallToolResult]]
        | None
    ) = None
