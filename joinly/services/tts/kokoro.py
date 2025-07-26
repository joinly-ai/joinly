import asyncio
import logging
import os
import pathlib
import re
from collections.abc import AsyncIterator
from typing import Self

from kokoro_onnx import Kokoro

from joinly.core import TTS
from joinly.settings import get_settings
from joinly.types import AudioFormat

logger = logging.getLogger(__name__)

_CHUNK_RE = re.compile(r"(?<=[.!?])\s+")


class KokoroTTS(TTS):
    """Text-to-Speech (TTS) service for converting text to speech."""

    def __init__(self, *, voice: str = "af_bella") -> None:
        """Initialize the TTS service.

        Args:
            voice: The voice to use for TTS (default is "af_bella" for English).
        """
        default_voices = {
            "en": "af_bella",
            "es": "ef_dora",
            "fr": "ff_siwis",
            "it": "if_sara",
        }
        if get_settings().language not in default_voices:
            logger.warning(
                "Unsupported language %s for Kokoro TTS, falling back to English.",
                get_settings().language,
            )
        self._voice = voice or default_voices.get(
            get_settings().language, default_voices["en"]
        )
        self._model: Kokoro | None = None
        self._sem = asyncio.BoundedSemaphore(1)
        self.audio_format = AudioFormat(sample_rate=24000, byte_depth=4)

    async def __aenter__(self) -> Self:
        """Load the TTS model."""
        cache_dir = (
            pathlib.Path(os.getenv("XDG_CACHE_HOME", "~/.cache")).expanduser()
            / "kokoro"
        )
        if not cache_dir.exists():
            msg = (
                f"Kokoro TTS cache directory {cache_dir} does not exist. "
                "Make sure to download the model first "
                "(uv run scripts/download_assets.py)."
            )
            raise RuntimeError(msg)

        logger.info("Loading TTS model from %s", cache_dir)
        self._model = await asyncio.to_thread(
            Kokoro,
            model_path=str(cache_dir / "kokoro-v1.0.onnx"),
            voices_path=str(cache_dir / "voices-v1.0.bin"),
        )
        logger.debug("Loaded TTS model")

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources."""
        if self._model is not None:
            del self._model
            self._model = None

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Convert text to speech and stream the audio data.

        Args:
            text: The text to convert to speech.

        Yields:
            bytes: The audio data for each text segment.
        """
        # further chunk down to speed up response time
        chunks = _CHUNK_RE.split(text)
        for chunk in chunks:
            audio_data = await self._tts(chunk)
            yield audio_data

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
