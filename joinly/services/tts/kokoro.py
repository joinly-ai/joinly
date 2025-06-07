import asyncio
import logging
import os
import pathlib
from collections.abc import AsyncIterator
from typing import Self

from kokoro_onnx import Kokoro

from joinly.core import TTS
from joinly.types import AudioFormat, IncompatibleAudioFormatError
from joinly.utils.audio import convert_byte_depth

logger = logging.getLogger(__name__)


class KokoroTTS(TTS):
    """Text-to-Speech (TTS) service for converting text to speech."""

    def __init__(self, *, voice: str = "af_bella") -> None:
        """Initialize the TTS service."""
        self._voice = voice
        self._model: Kokoro | None = None
        self._sem = asyncio.BoundedSemaphore(1)

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

    async def stream(
        self, text: str, audio_format: AudioFormat
    ) -> AsyncIterator[bytes]:
        """Convert text to speech and stream the audio data.

        Args:
            text: The text to convert to speech.
            audio_format: The format of the audio data to be returned.

        Yields:
            bytes: The audio data for each text segment.
        """
        if audio_format.sample_rate != 24000:  # noqa: PLR2004
            msg = f"Unsupported sample rate {audio_format.sample_rate}, expected 24000"
            raise IncompatibleAudioFormatError(msg)

        audio_data = await self._tts(text)
        audio_data = convert_byte_depth(audio_data, 4, audio_format.byte_depth)
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
