import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Literal

logger = logging.getLogger(__name__)

type EventType = Literal["segment", "utterance"]


class EventBus:
    """A lightweight event bus for publishing and subscribing to typed events."""

    def __init__(self) -> None:
        """Initialize the event bus."""
        self._listeners: dict[
            EventType, set[Callable[[], Coroutine[None, None, None]]]
        ] = {}

    def subscribe(
        self,
        event_type: EventType,
        handler: Callable[[], Coroutine[None, None, None]],
    ) -> Callable[[], None]:
        """Subscribe to an event type.

        Args:
            event_type: The type of event to listen for.
            handler: An async function that will be called when the event occurs.

        Returns:
            A function that can be called to unsubscribe this handler.
        """
        if event_type not in self._listeners:
            self._listeners[event_type] = set()

        self._listeners[event_type].add(handler)

        def unsubscribe() -> None:
            if event_type in self._listeners:
                self._listeners[event_type].discard(handler)
                if not self._listeners[event_type]:
                    del self._listeners[event_type]

        return unsubscribe

    def publish(self, event_type: EventType) -> None:
        """Publish an event to all subscribers.

        Args:
            event_type: The type of event being published.
        """
        if event_type not in self._listeners:
            return

        for handler in list(self._listeners[event_type]):
            asyncio.create_task(self._safe_call_handler(handler))  # noqa: RUF006

    async def _safe_call_handler(
        self,
        handler: Callable[[], Coroutine[None, None, None]],
    ) -> None:
        """Safely call an event handler, logging any exceptions.

        Args:
            handler: The handler function to call.
            event_type: The event type to pass to the handler.
        """
        try:
            await handler()
        except Exception:
            logger.exception("Error in event handler: %s", handler)
