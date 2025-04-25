import asyncio
import logging
from collections.abc import AsyncIterator
from functools import partial
from typing import override

import numpy as np
from faster_whisper import WhisperModel

from meeting_agent.core.async_processor import AsyncBufferedProcessor

logger = logging.getLogger(__name__)


class AudioTranscriber(AsyncBufferedProcessor[bytes, str]):
    """A class to transcribe audio using Whisper."""

    def __init__(self, upstream: AsyncIterator[bytes]) -> None:
        """Initialize the AudioTranscriber."""
        super().__init__(upstream, buffer_size=5)
        self._model: WhisperModel | None = None
        self._sem = asyncio.Semaphore(1)

    @override
    async def on_start(self) -> None:
        """Initialize the Whisper model."""
        self._model = await asyncio.to_thread(
            WhisperModel,
            "small",
            device="cpu",
            compute_type="int8",
        )

    @override
    async def process(self, item: bytes) -> AsyncIterator[str]:
        """Process the input audio chunk and yield transcriptions.

        Args:
            item: Audio data in bytes format.

        Yields:
            str: Transcription of the audio segment.

        TODO: condition on previous text
        """
        if self._model is None:
            msg = "Model not initialized"
            raise RuntimeError(msg)

        audio_segment = np.frombuffer(item, dtype=np.float32)
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
            yield seg.text.strip()
