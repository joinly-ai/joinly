import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator
from typing import Self

import torch

from meeting_agent.utils import LOGGING_TRACE

logger = logging.getLogger(__name__)


class VADService(AsyncIterator[tuple[bytes, float, float]]):
    """A class to detect speech in audio streams and chunk audio bytes."""

    def __init__(
        self,
        upstream: AsyncIterator[bytes],
        *,
        speech_threshold: float = 0.75,
        max_silent_chunks: int = 12,
        padding_chunks: int = 2,
    ) -> None:
        """Initialize the VADService.

        Args:
            upstream: An AsyncIterator that provides audio data.
            speech_threshold: The threshold for speech detection (default is 0.75).
            max_silent_chunks: Max number of silent chunks each 32ms (default is 12).
            padding_chunks: Number of chunks to add before/after speech (default is 2).
        """
        self._upstream = upstream
        self._speech_threshold = speech_threshold
        self._max_silent_chunks = max_silent_chunks
        self._padding_chunks = padding_chunks
        self._silent_chunks: int = 0
        self._speech_chunks: int = 0
        self._chunks: int = 0
        self._start_chunk: int = 0
        self._prev_buffer: deque[bytes] = deque(maxlen=padding_chunks)
        self._buffer: list[bytes] = []
        self._model = None
        self.no_speech_event = asyncio.Event()

    async def __aenter__(self) -> Self:
        """Initialize the VAD model and prepare for processing."""
        logger.info("Loading VAD model")
        self._model, _ = await asyncio.to_thread(
            torch.hub.load,
            "snakers4/silero-vad",
            model="silero_vad",
        )  # type: ignore[no-untyped-call]
        self._model = self._model.to("cpu")
        self._model.reset_states()
        logger.info("Loaded VAD model")

        self._silent_chunks = 0
        self._speech_chunks = 0
        self._chunks = 0
        self._start_chunk = 0
        self._prev_buffer.clear()
        self._buffer.clear()
        self.no_speech_event.set()

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources when stopping the processor."""
        if self._model is not None:
            del self._model
            self._model = None

    async def __anext__(self) -> tuple[bytes, float, float]:
        """Get the next audio chunk from the upstream source.

        Returns:
            bytes: The next audio chunk.

        Raises:
            StopAsyncIteration: If there are no more chunks to process.
        """
        while True:
            chunk = await self._upstream.__anext__()
            result = await self._process(chunk)
            if result is not None:
                return result

    async def _process(self, chunk: bytes) -> tuple[bytes, float, float] | None:
        """Process the input audio chunk and yield speech segments.

        Args:
            chunk: Audio data in bytes format.

        Returns:
            bytes: Audio segment of concurrent speech.

        TODO: make faster: maybe directly yield chunks instead of buffer?
            if whisper can handle that
        """
        confidence = await self._vad(chunk)
        speech = confidence > self._speech_threshold

        logger.log(
            LOGGING_TRACE,
            "%s %s: %s (%.2f)",
            self._silent_chunks,
            self._speech_chunks,
            speech,
            confidence,
        )

        if speech:
            self._silent_chunks = 0
            self._speech_chunks += 1
            if self._speech_chunks == 1:
                self.no_speech_event.clear()
                self._start_chunk = self._chunks
                logger.info("Speech started")
        else:
            self._silent_chunks += 1
        self._chunks += 1

        if not self._buffer:
            self._prev_buffer.append(chunk)
            if speech:
                self._buffer.extend(self._prev_buffer)
                self._prev_buffer.clear()
        else:
            self._buffer.append(chunk)
            if self._silent_chunks >= self._max_silent_chunks:
                tail = self._silent_chunks - self._padding_chunks
                segment = b"".join(self._buffer[: -tail if tail > 0 else None])

                start_time = (self._start_chunk - self._padding_chunks) * 0.032
                end_time = start_time + (len(self._buffer) - max(0, tail)) * 0.032

                self._speech_chunks = 0
                self._buffer.clear()
                self.no_speech_event.set()
                logger.info("Speech ended")

                return segment, start_time, end_time

        return None

    @torch.no_grad()
    async def _vad(self, audio_bytes: bytes) -> float:
        """Run VAD on the audio data.

        Args:
            audio_bytes: Audio data in bytes format.

        Returns:
            float: Confidence score for speech detection.
        """
        if self._model is None:
            msg = "VAD model not initialized"
            raise RuntimeError(msg)

        audio_f32 = torch.frombuffer(bytearray(audio_bytes), dtype=torch.float32)
        confidence = await asyncio.to_thread(self._model, audio_f32, 16000)

        return confidence.item()
