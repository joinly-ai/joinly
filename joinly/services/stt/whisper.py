import asyncio
import logging
from collections.abc import AsyncIterator
from functools import partial
from typing import Self

import numpy as np
from faster_whisper import WhisperModel

from joinly.core import STT
from joinly.settings import get_settings
from joinly.types import TranscriptSegment, VADWindow

logger = logging.getLogger(__name__)


class WhisperSTT(STT):
    """A class to transcribe audio using Whisper."""

    def __init__(
        self,
        *,
        model_name: str = "tiny.en",
        min_audio: float = 0.4,
        min_silence: float = 0.2,
        hotwords: list[str] | None = None,
    ) -> None:
        """Initialize the WhisperSTT.

        Args:
            model_name: The Whisper model to use (default is "tiny.en").
            min_audio: Minimum audio length (in seconds) to consider for transcription.
            min_silence: Minimum silence length (in seconds) to consider before ending
                a segment.
            hotwords: A list of hotwords to improve transcription accuracy.
        """
        self._model_name = model_name
        self._min_audio = min_audio
        self._min_silence = min_silence
        hotwords_arr = (hotwords or []) + [get_settings().name]
        self._hotwords_str = " ".join(hotwords_arr)
        self._model: WhisperModel | None = None
        self._sem = asyncio.BoundedSemaphore(1)

    async def __aenter__(self) -> Self:
        """Initialize the Whisper model."""
        logger.info("Initializing Whisper model")

        self._model = await asyncio.to_thread(
            WhisperModel,
            self._model_name,
            device="cpu",
            compute_type="int8",
        )

        logger.info("Initialized Whisper model")

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources when stopping the processor."""
        if self._model is not None:
            del self._model
            self._model = None

    async def stream(
        self, windows: AsyncIterator[VADWindow]
    ) -> AsyncIterator[TranscriptSegment]:
        """Stream audio windows and yield transcribed segments.

        Args:
            windows: An AsyncIterator of VADWindow objects.

        Yields:
            TranscriptSegment: The transcribed segments.
        """
        if self._model is None:
            msg = "Model not initialized"
            raise RuntimeError(msg)

        queue = asyncio.Queue[tuple[bytes, float] | None](maxsize=10)
        buffer_task = asyncio.create_task(self._buffer_windows(windows, queue))

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                pcm, start = item
                async for segment in self._transcribe(pcm, start):
                    yield segment
        finally:
            buffer_task.cancel()

    async def _buffer_windows(
        self,
        windows: AsyncIterator[VADWindow],
        queue: asyncio.Queue[tuple[bytes, float] | None],
    ) -> None:
        """Buffer audio windows into the queue.

        Args:
            windows: An AsyncIterator of VADWindow objects.
            queue: The queue to put buffered audio chunks into.
        """
        buffer = bytearray()
        start: float = -1
        silence_bytes: int = 0
        min_bytes: int = int(16000 * 4 * self._min_audio)
        min_silence_bytes: int = int(16000 * 4 * self._min_silence)

        async for window in windows:
            if window.is_speech and start < 0:
                start = window.start

            if start >= 0:
                buffer.extend(window.pcm)
                if window.is_speech:
                    silence_bytes = 0
                else:
                    silence_bytes += len(window.pcm)

                if len(buffer) >= min_bytes and silence_bytes >= min_silence_bytes:
                    logger.debug(
                        "Buffering audio chunk of size: %d (%.2fs)",
                        len(buffer),
                        len(buffer) / (16000 * 4),
                    )
                    await queue.put((bytes(buffer), start))
                    buffer.clear()
                    start = -1
                    silence_bytes = 0

        if start >= 0 and buffer:
            await queue.put((bytes(buffer), start))
        await queue.put(None)

    async def _transcribe(
        self, pcm: bytes, start: float
    ) -> AsyncIterator[TranscriptSegment]:
        """Process the input audio chunk and yield transcriptions.

        Args:
            pcm: Audio data in bytes format.
            start: The start time of the audio segment.

        Yields:
            TranscriptSegment: The transcribed segment.
        """
        if self._model is None:
            msg = "Model not initialized"
            raise RuntimeError(msg)

        async with self._sem:
            logger.info(
                "Processing audio chunk of size: %d (%.2fs)",
                len(pcm),
                len(pcm) / (16000 * 4),
            )

            audio_segment = np.frombuffer(pcm, dtype=np.float32)
            segments, _ = await asyncio.to_thread(
                self._model.transcribe,
                audio_segment,
                language="en",
                beam_size=5,
                condition_on_previous_text=False,
                hotwords=self._hotwords_str,
            )

            get_next_segment = partial(next, iter(segments), None)
            while True:
                seg = await asyncio.to_thread(get_next_segment)
                if seg is None:
                    break

                text = seg.text.strip()
                if text:
                    yield TranscriptSegment(
                        text=text,
                        start=start + seg.start,
                        end=start + seg.end,
                    )
