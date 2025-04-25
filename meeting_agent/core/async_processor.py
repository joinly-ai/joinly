import abc
import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Generic, Self, TypeVar, override

InT = TypeVar("InT")
OutT = TypeVar("OutT")

_SENTINEL = object()


class AsyncProcessor(
    Generic[InT, OutT],
    AsyncIterator[OutT],
    contextlib.AbstractAsyncContextManager,
    metaclass=abc.ABCMeta,
):
    """Transform stream of InT to OutT."""

    def __init__(self, upstream: AsyncIterator[InT]) -> None:
        """Initialize the processor with upstream source.

        Args:
            upstream: Source iterator providing input items
        """
        self._upstream = upstream
        self._sub_iter: AsyncIterator[OutT] | None = None

    async def __aenter__(self) -> Self:
        """Set up async context and initialize queue processing if needed."""
        await self.on_start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources when exiting the async context manager."""
        await self.on_stop()

    async def __anext__(self) -> OutT:
        """Return the next output item from the processing pipeline."""
        while True:
            if self._sub_iter is None:
                item = await self._get_input()
                self._sub_iter = self.process(item)

            try:
                return await self._sub_iter.__anext__()
            except StopAsyncIteration:
                self._sub_iter = None

    async def _get_input(self) -> InT:
        return await self._upstream.__anext__()

    @abc.abstractmethod
    async def process(self, item: InT) -> AsyncIterator[OutT]:
        """Transform a single input into zero or more outputs."""
        yield  # type: ignore[no-any-return]

    async def on_start(self) -> None:
        """Override for async startup logic."""

    async def on_stop(self) -> None:
        """Override for async teardown logic."""


class AsyncBufferedProcessor(AsyncProcessor[InT, OutT]):
    """Base class for processors with input buffering."""

    def __init__(
        self,
        upstream: AsyncIterator[InT],
        buffer_size: int,
    ) -> None:
        """Initialize the processor with upstream source and queue buffer."""
        super().__init__(upstream)
        self._buffer_size = buffer_size
        self._buffer: asyncio.Queue[InT | object] | None = None
        self._buffer_task: asyncio.Task | None = None

    @override
    async def __aenter__(self) -> Self:
        """Set up async context and initialize queue processing if needed."""
        await super().__aenter__()

        if self._buffer_size is not None:
            self._buffer = asyncio.Queue[InT | object](self._buffer_size)
            self._buffer_task = asyncio.create_task(self._fill_buffer())
        return self

    @override
    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources when exiting the async context manager."""
        if self._buffer_task:
            self._buffer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._buffer_task

        await super().__aexit__(*_exc)

    @override
    async def _get_input(self) -> InT:
        if self._buffer is None:
            msg = "Buffer is not initialized"
            raise RuntimeError(msg)

        item = await self._buffer.get()
        if item is _SENTINEL:
            raise StopAsyncIteration
        return item  # type: ignore[return-value]

    async def _fill_buffer(self) -> None:
        """Continuously transfer data from upstream to buffer queue."""
        if self._buffer is None:
            msg = "Buffer is not initialized"
            raise RuntimeError(msg)

        try:
            async for item in self._upstream:
                await self._buffer.put(item)
            await self._buffer.put(_SENTINEL)
        except asyncio.CancelledError:
            pass
