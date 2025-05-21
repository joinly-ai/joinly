import asyncio
import logging
import os
import pathlib
import re
from collections.abc import AsyncIterator
from typing import Self

from kokoro_onnx import Kokoro

logger = logging.getLogger(__name__)


class TTSService:
    """Text-to-Speech (TTS) service for converting text to speech."""

    def __init__(self, *, voice: str = "af_bella") -> None:
        """Initialize the TTS service."""
        self._voice = voice
        self._model: Kokoro | None = None
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

    async def tts(self, text: str) -> AsyncIterator[tuple[bytes, str]]:
        """Convert text to speech and stream the audio data."""
        logger.info("Streaming TTS for text: %s", text)

        chunks = re.split(r"(?<=[.,;!?])\s+", text)
        for chunk in chunks:
            audio_data = await self._tts(chunk)
            yield audio_data, chunk

        logger.info("Finished streaming TTS for text: %s", text)

    async def _tts(self, text: str) -> bytes:
        """Convert text to speech."""
        if self._model is None:
            msg = "Model not initialized"
            raise RuntimeError(msg)

        async with self._sem:
            return await asyncio.to_thread(
                lambda text: self._model.create(text, voice=self._voice)[0].tobytes(),  # type: ignore[attr-defined]
                text,
            )
