import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Self

import numpy as np
from silero_vad_lite import SileroVAD as SileroVADModel

from joinly.core import VAD, AudioReader
from joinly.types import VADWindow

logger = logging.getLogger(__name__)


class SileroVAD(VAD):
    """A class to detect speech in audio streams and chunk audio bytes."""

    def __init__(
        self,
        *,
        speech_threshold: float = 0.5,
    ) -> None:
        """Initialize the VADService.

        Args:
            speech_threshold: The threshold for speech detection (default is 0.5).
        """
        self._speech_threshold = speech_threshold
        self._model: SileroVADModel | None = None

    async def __aenter__(self) -> Self:
        """Initialize the VAD model and prepare for processing."""
        logger.info("Loading VAD model")
        self._model = await asyncio.to_thread(
            SileroVADModel,
            16000,
        )
        logger.info("Loaded VAD model")

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources when stopping the processor."""
        if self._model is not None:
            del self._model
            self._model = None

    async def stream(self, reader: AudioReader) -> AsyncIterator[VADWindow]:  # noqa: C901
        """Process the audio stream and yield speech segments.

        For non-speech segments, keeps one window in buffer to mark one previous
        window as well as speech.

        Args:
            reader: An AudioReader providing audio data.

        Yields:
            VADFrame: A frame containing the audio segment, start time, and end time.
        """
        if self._model is None:
            msg = "VAD model not initialized"
            raise RuntimeError(msg)

        if reader.sample_rate != self._model.sample_rate:
            msg = (
                f"Expected sample rate {self._model.sample_rate}, "
                f"got {reader.sample_rate}"
            )
            raise ValueError(msg)
        if reader.byte_depth not in (2, 4):
            msg = f"Unsupported byte depth: {reader.byte_depth}"
            raise ValueError(msg)

        idx: int = 0
        window_size: int = self._model.window_size_samples * reader.byte_depth
        chunk_dur: float = self._model.window_size_samples / reader.sample_rate
        buffer = bytearray()
        pending: bytes = b""
        last_is_speech: bool = False

        while True:
            chunk = await reader.read()
            if not chunk:
                break
            buffer.extend(chunk)

            while len(buffer) >= window_size:
                window_bytes = bytes(buffer[:window_size])
                if reader.byte_depth == 4:  # noqa: PLR2004
                    samples = np.frombuffer(window_bytes, dtype=np.float32)
                else:
                    arr16 = np.frombuffer(window_bytes, dtype=np.int16)
                    samples = arr16.astype(np.float32) / 32768.0

                prob = await asyncio.to_thread(self._model.process, samples)
                is_speech = prob > self._speech_threshold

                if not is_speech:
                    if pending:
                        yield VADWindow(
                            pcm=pending,
                            start=(idx - 1) * chunk_dur,
                            is_speech=last_is_speech,
                        )
                    pending = bytes(window_bytes)
                else:
                    if pending:
                        yield VADWindow(
                            pcm=pending,
                            start=(idx - 1) * chunk_dur,
                            is_speech=True,
                        )
                    pending = b""

                    yield VADWindow(
                        pcm=bytes(window_bytes),
                        start=idx * chunk_dur,
                        is_speech=True,
                    )

                del buffer[:window_size]
                idx += 1
                last_is_speech = is_speech
