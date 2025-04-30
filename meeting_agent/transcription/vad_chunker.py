import asyncio
import logging
from collections.abc import AsyncIterator
from typing import override

import torch

from meeting_agent.shared.async_processor import AsyncProcessor

logger = logging.getLogger(__name__)


class VADChunker(AsyncProcessor[bytes, bytes]):
    """A class to detect speech in audio streams and chunk audio bytes."""

    def __init__(
        self,
        upstream: AsyncIterator[bytes],
        speech_threshold: float = 0.5,
        max_silent_chunks: int = 15,
    ) -> None:
        """Initialize the VADChunker.

        Args:
            upstream: An AsyncIterator that provides audio data.
            speech_threshold: The threshold for speech detection (default is 0.5).
            max_silent_chunks: Max number of silent chunks each 32ms (default is 15).
        """
        super().__init__(upstream)
        self._model = None
        self._speech_threshold = speech_threshold
        self._max_silent_chunks = max_silent_chunks
        self._buffer = bytearray()
        self._silent_chunks = 0
        self._had_speech = False

    @override
    async def on_start(self) -> None:
        self._model, _ = await asyncio.to_thread(
            torch.hub.load,
            "snakers4/silero-vad",
            model="silero_vad",
            source="github",
        )  # type: ignore[no-untyped-call]
        self._model = self._model.to("cpu")
        self._model.reset_states()

        self._buffer.clear()
        self._silent_chunks = 0
        self._had_speech = False

    @override
    async def process(self, item: bytes) -> AsyncIterator[bytes]:
        """Process the input audio chunk and yield speech segments.

        Args:
            item: Audio data in bytes format.

        Yields:
            bytes: Audio segment of concurrent speech.

        TODO: improve for not adding the silence in the end, add padding
        to start and end but do not extend buffer with all silence (limit)
        """
        confidence = await self._vad(item)
        speech = confidence > self._speech_threshold

        logger.info(
            "%s %s: %s (%.2f)",
            self._had_speech,
            self._silent_chunks,
            speech,
            confidence,
        )

        self._had_speech = self._had_speech | speech
        if self._had_speech:
            self._buffer.extend(item)

        if speech:
            self._silent_chunks = 0
        else:
            self._silent_chunks += 1
            if self._silent_chunks >= self._max_silent_chunks and self._had_speech:
                buffer_bytes = bytes(self._buffer)
                self._buffer.clear()
                self._silent_chunks = 0
                self._had_speech = False
                yield buffer_bytes

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

        audio_f32 = torch.frombuffer(audio_bytes, dtype=torch.float32)
        confidence = await asyncio.to_thread(self._model, audio_f32, 16000)

        return confidence.item()
