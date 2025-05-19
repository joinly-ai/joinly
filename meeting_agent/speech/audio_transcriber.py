import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import partial
from typing import Self

import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

_SENTINEL = object()


class AudioTranscriber:
    """A class to transcribe audio using Whisper."""

    def __init__(self, upstream: AsyncIterator[bytes]) -> None:
        """Initialize the AudioTranscriber."""
        self._upstream = upstream
        self._model: WhisperModel | None = None
        self._sem = asyncio.Semaphore(1)
        self._queue: asyncio.Queue[bytes | object] | None = None
        self._queue_task: asyncio.Task | None = None
        self._process_task: asyncio.Task | None = None
        self._listeners: set[Callable[[str, str], Awaitable[None]]] = set()
        self._transcript: list[str] = []

    def add_listener(
        self, listener: Callable[[str, str], Awaitable[None]]
    ) -> Callable[[], None]:
        """Add a listener for a specific event."""
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    @property
    def transcript(self) -> str:
        """Get the current transcript."""
        return " ".join(self._transcript)

    async def __aenter__(self) -> Self:
        """Initialize the Whisper model."""
        logger.info("Initializing Whisper model")

        self._model = await asyncio.to_thread(
            WhisperModel,
            "small",
            device="cpu",
            compute_type="int8",
        )

        logger.info("Initialized Whisper model")

        self._queue = asyncio.Queue[bytes | object](maxsize=5)
        self._queue_task = asyncio.create_task(self._fill_queue())
        self._process_task = asyncio.create_task(self._process_queue())

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources when stopping the processor."""
        if self._queue_task:
            self._queue_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._queue_task
            self._queue_task = None
            self._queue = None
        if self._process_task:
            self._process_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._process_task
            self._process_task = None

        if self._model is not None:
            del self._model
            self._model = None

    async def _notify(self, event: str, text: str) -> None:
        """Notify all listeners."""
        for listener in self._listeners:
            await listener(event, text)

    async def _fill_queue(self) -> None:
        """Fill the queue with audio data."""
        if self._queue is None:
            msg = "Queue not initialized"
            raise RuntimeError(msg)

        with contextlib.suppress(asyncio.CancelledError):
            async for item in self._upstream:
                await self._queue.put(item)
            await self._queue.put(_SENTINEL)

    async def _process_queue(self) -> None:
        """Process the audio data in the queue."""
        if self._queue is None:
            msg = "Queue not initialized"
            raise RuntimeError(msg)

        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                break

            segment = []
            async for chunk in self.transcribe(item):  # type: ignore[arg-type]
                logger.debug("Transcription chunk: %s", chunk)
                segment.append(chunk)
                self._transcript.append(chunk)
                await self._notify("chunk", chunk)

            if segment:
                logger.info("Transcription segment: %s", " ".join(segment))
                await self._notify("segment", " ".join(segment))

        await self._queue.put(_SENTINEL)

    async def transcribe(self, item: bytes) -> AsyncIterator[str]:
        """Process the input audio chunk and yield transcriptions.

        Args:
            item: Audio data in bytes format.

        Yields:
            str: Transcription of the audio segment.

        TODO: condition on previous text; stream input directly?
        """
        if self._model is None:
            msg = "Model not initialized"
            raise RuntimeError(msg)

        async with self._sem:
            logger.info("Processing audio chunk of size: %d", len(item))

            audio_segment = np.frombuffer(item, dtype=np.float32)

            # probably rather take whisper completely out to another process/api
            segments, _ = await asyncio.to_thread(
                self._model.transcribe,
                audio_segment,
                language="en",
                beam_size=5,
                condition_on_previous_text=False,
            )

            get_next_segment = partial(next, iter(segments), None)
            while True:
                seg = await asyncio.to_thread(get_next_segment)
                if seg is None:
                    break

                text = seg.text.strip()
                if text:
                    yield text
