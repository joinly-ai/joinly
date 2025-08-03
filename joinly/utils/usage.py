import logging
from contextvars import ContextVar, Token

from joinly.types import Usage

logger = logging.getLogger(__name__)


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
    current_usage.add(service, usage=usage, meta=meta)
