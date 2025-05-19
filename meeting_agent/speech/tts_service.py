import asyncio
import logging
import os
import pathlib
from collections.abc import AsyncIterator
from typing import Self

from blingfire import text_to_sentences
from kokoro_onnx import Kokoro

logger = logging.getLogger(__name__)


class TTSService:
    """Text-to-Speech (TTS) service for converting text to speech."""

    def __init__(self, *, voice: str = "af_kore") -> None:
        """Initialize the TTS service."""
        self._voice = voice
        self._model = None
        self._sem = asyncio.Semaphore(1)

    async def __aenter__(self) -> Self:
        """Load the TTS model."""
        cache_dir = (
            pathlib.Path(os.getenv("XDG_CACHE_HOME", "~/.cache")).expanduser()
            / "kokoro"
        )
        if not cache_dir.exists():
            msg = f"TTS cache directory {cache_dir} does not exist"
            raise RuntimeError(msg)

        logger.info("Loading TTS model from %s", cache_dir)
        self._model = await asyncio.to_thread(
            Kokoro,
            model_path=str(cache_dir / "kokoro-v1.0.onnx"),
            voices_path=str(cache_dir / "voices-v1.0.bin"),
        )
        logger.info("Loaded TTS model")

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources."""
        if self._model is not None:
            del self._model
            self._model = None

    async def tts(self, text: str) -> AsyncIterator[bytes]:
        """Stream TTS audio."""
        if self._model is None:
            msg = "Model not initialized"
            raise RuntimeError(msg)

        logger.info("Streaming TTS for text: %s", text)

        sentences = text_to_sentences(text).split("\n")
        async with self._sem:
            for sentence in sentences:
                tts_stream = self._model.create_stream(sentence, voice=self._voice)
                async for pcm_array, _ in tts_stream:
                    pcm_bytes = await asyncio.to_thread(pcm_array.tobytes)
                    logger.debug("Yielding PCM bytes of size %d", len(pcm_bytes))
                    yield pcm_bytes

        logger.info("Finished streaming TTS for text: %s", text)
