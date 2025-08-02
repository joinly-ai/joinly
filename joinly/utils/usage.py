import logging
from contextvars import ContextVar, Token
from typing import Self

from pydantic import BaseModel, Field, RootModel

logger = logging.getLogger(__name__)


class ServiceUsage(BaseModel):
    """Dataclass to hold usage statistics for a service."""

    usage: dict[str, int | float]
    meta: dict[str, str | int | float] = Field(default_factory=dict)

    def add(self, usage: Self) -> None:
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

    def add(self, service: str, usage: ServiceUsage) -> None:
        """Add usage statistics for a specific service.

        Args:
            service: The name of the service.
            usage: A ServiceUsage instance containing the usage statistics.
        """
        if service not in self.root:
            self.root[service] = usage
        else:
            self.root[service].add(usage)

    def __str__(self) -> str:
        """Return a string representation of the Usage instance."""
        return "\n".join(f"{service}: {usage}" for service, usage in self.root.items())


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
    current_usage.add(
        service,
        ServiceUsage(usage=usage, meta=meta) if meta else ServiceUsage(usage=usage),
    )
