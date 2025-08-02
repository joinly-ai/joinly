import logging
from contextvars import ContextVar, Token
from typing import Self

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ServiceUsage(BaseModel):
    """Dataclass to hold usage statistics for a service."""

    usage: dict[str, int | float]
    meta: dict[str, str | int | float] = Field(default_factory=dict)

    def add(self, usage: Self) -> None:
        """Add usage statistics from another ServiceUsage instance."""
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


Usage = dict[str, ServiceUsage]

_current_usage: ContextVar[Usage] = ContextVar("current_usage", default=Usage())  # noqa: B039


def get_usage() -> Usage:
    """Get the current usage statistics.

    Returns:
        Usage: The current usage statistics.
    """
    return _current_usage.get()


def set_usage(usage: Usage) -> Token[Usage]:
    """Set the current usage statistics.

    Args:
        usage: The usage statistics to set.

    Returns:
        Token[Usage]: A token that can be used to reset the usage statistics.
    """
    return _current_usage.set(usage)


def reset_usage(token: Token[Usage]) -> None:
    """Reset the current usage statistics.

    Args:
        token: The token returned by `set_usage`.
    """
    _current_usage.reset(token)


def add_usage(
    service: str,
    usage: dict[str, int | float],
    meta: dict[str, str | int | float] | None = None,
) -> None:
    """Add usage statistics for a service.

    Args:
        service: The name of the service.
        usage: A dictionary containing usage statistics.
        meta: Additional metadata about the usage.
    """
    current_usage = get_usage()
    service_usage = (
        ServiceUsage(usage=usage, meta=meta) if meta else ServiceUsage(usage=usage)
    )
    if service not in current_usage:
        current_usage[service] = service_usage
    else:
        current_usage[service].add(service_usage)


def log_usage() -> None:
    """Log the current usage statistics."""
    current_usage = get_usage()
    for service, usage in current_usage.items():
        logger.info("%s: %s", service, usage)
