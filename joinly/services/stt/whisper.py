import asyncio
import logging
from collections.abc import AsyncIterator
from functools import partial
from typing import Self

import numpy as np
from faster_whisper import WhisperModel

from joinly.core import STT
from joinly.settings import get_settings
from joinly.types import (
    AudioFormat,
    SpeechWindow,
    TranscriptSegment,
)
from joinly.utils.audio import calculate_audio_duration

logger = logging.getLogger(__name__)


class WhisperSTT(STT):
    """A class to transcribe audio using Whisper."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        compute_type: str = "auto",
        min_audio: float = 0.4,
        min_silence: float = 0.2,
        hotwords: list[str] | None = None,
    ) -> None:
        """Initialize the WhisperSTT.

        Args:
            model_name: The Whisper model to use (default is None, where for cpu it
                uses "base.en" and for cuda "distil-large-v3").
            compute_type: The compute type for the model (default is "auto").
            min_audio: Minimum audio length (in seconds) to consider for transcription.
            min_silence: Minimum silence length (in seconds) to consider before ending
                a segment.
            hotwords: A list of hotwords to improve transcription accuracy.
        """
        self.model_name = model_name or (
            "distil-large-v3" if get_settings().device == "cuda" else "base.en"
        )
        self._set_model_name = model_name is not None
        self.compute_type = compute_type
        self.min_audio = min_audio
        self.min_silence = min_silence
        hotwords_arr = (hotwords or []) + [get_settings().name]
        self._hotwords_str = " ".join(hotwords_arr)
        self.audio_format = AudioFormat(sample_rate=16000, byte_depth=4)
        self._model: WhisperModel | None = None
        self._sem = asyncio.BoundedSemaphore(1)

    async def __aenter__(self) -> Self:
        """Initialize the Whisper model."""
        logger.info(
            "Initializing Whisper model: %s, device: %s, compute type: %s",
            self.model_name,
            get_settings().device,
            self.compute_type,
        )

        self._model = await asyncio.to_thread(
            WhisperModel,
            self.model_name,
            device=get_settings().device,
            compute_type=self.compute_type,
            local_files_only=not self._set_model_name,
        )

        logger.info("Initialized Whisper model")

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources when stopping the processor."""
        if self._model is not None:
            del self._model
            self._model = None

    async def stream(
        self, windows: AsyncIterator[SpeechWindow]
    ) -> AsyncIterator[TranscriptSegment]:
        """Stream audio windows and yield transcribed segments.

        Args:
            windows: An AsyncIterator of SpeechWindow objects.

        Yields:
            TranscriptSegment: The transcribed segments.
        """
        if self._model is None:
            msg = "Model not initialized"
            raise RuntimeError(msg)

        queue = asyncio.Queue[tuple[bytes, float, float] | None](maxsize=10)
        buffer_task = asyncio.create_task(self._buffer_windows(windows, queue))

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                data, start, end = item
                async for segment in self._transcribe(data, start, end):
                    yield segment
        finally:
            buffer_task.cancel()

    async def _buffer_windows(
        self,
        windows: AsyncIterator[SpeechWindow],
        queue: asyncio.Queue[tuple[bytes, float, float] | None],
    ) -> None:
        """Buffer audio windows into the queue.

        Args:
            windows: An AsyncIterator of SpeechWindow objects.
            queue: The queue to put buffered audio chunks into.
        """
        buffer = bytearray()
        start: float = -1
        silence_bytes: int = 0
        min_bytes: int = int(16000 * 4 * self.min_audio)
        min_silence_bytes: int = int(16000 * 4 * self.min_silence)

        async for window in windows:
            if window.is_speech and start < 0:
                start = window.start

            if start >= 0:
                buffer.extend(window.data)
                if window.is_speech:
                    silence_bytes = 0
                else:
                    silence_bytes += len(window.data)

                if len(buffer) >= min_bytes and silence_bytes >= min_silence_bytes:
                    logger.debug(
                        "Buffering audio chunk of size: %d (%.2fs)",
                        len(buffer),
                        len(buffer) / (16000 * 4),
                    )
                    end = window.start + int(len(window.data) / (16000 * 4))
                    await queue.put((bytes(buffer), start, end))
                    buffer.clear()
                    start = -1
                    silence_bytes = 0

        if start >= 0 and buffer:
            end = start + int(len(buffer) / (16000 * 4))
            await queue.put((bytes(buffer), start, end))
        await queue.put(None)

    async def _transcribe(
        self, data: bytes, start: float, end: float | None = None
    ) -> AsyncIterator[TranscriptSegment]:
        """Process the input audio chunk and yield transcriptions.

        Args:
            data: Audio data in bytes format.
            start: The start time of the audio segment.
            end: The end time of the audio segment.

        Yields:
            TranscriptSegment: The transcribed segment.
        """
        if self._model is None:
            msg = "Model not initialized"
            raise RuntimeError(msg)

        async with self._sem:
            logger.info(
                "Processing audio chunk of size: %d (%.2fs)",
                len(data),
                calculate_audio_duration(len(data), self.audio_format),
            )

            audio_segment = np.frombuffer(data, dtype=np.float32)
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
                        start=min(start + seg.start, end or float("inf")),
                        end=min(start + seg.end, end or float("inf")),
                    )
