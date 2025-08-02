import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Self

from elevenlabs.client import AsyncElevenLabs

from joinly.core import TTS
from joinly.settings import get_settings
from joinly.types import AudioFormat

logger = logging.getLogger(__name__)

DEFAULT_VOICES = defaultdict(
    lambda: "XrExE9yKIg1WjnnlVkGX",
    {
        "de": "1iF3vHdwHKuVKSPDK23Z",
        "en": "XrExE9yKIg1WjnnlVkGX",
    },
)


class ElevenlabsTTS(TTS):
    """Text-to-Speech (TTS) service for converting text to speech."""

    def __init__(
        self,
        *,
        voice_id: str | None = None,
        model_id: str = "eleven_flash_v2_5",
        sample_rate: int = 24000,
    ) -> None:
        """Initialize the TTS service.

        Args:
            voice_id: The ElevenLabs voice ID to use.
            model_id: The ElevenLabs model ID to use (default is "eleven_flash_v2_5").
            sample_rate: The sample rate of the audio (default is 24000).
        """
        self._voice_id = voice_id or DEFAULT_VOICES[get_settings().language]
        self._model_id = model_id
        self._output_format = f"pcm_{sample_rate}"
        self._client = AsyncElevenLabs()
        self._lock = asyncio.Lock()
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=2)
        self._usage_characters: int = 0

    async def __aenter__(self) -> Self:
        """Enter the asynchronous context manager."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the asynchronous context manager."""
        logger.info(
            "TTS ElevenLabs usage: %d characters",
            self._usage_characters,
        )

    def stream(self, text: str) -> AsyncIterator[bytes]:
        """Convert text to speech and stream the audio data.

        Args:
            text: The text to convert to speech.

        Returns:
            AsyncIterator[bytes]: An asynchronous iterator that yields audio chunks.
        """
        language_code = None
        if self._model_id in ("eleven_flash_v2_5", "eleven_turbo_v2_5"):
            language_code = get_settings().language

        self._usage_characters += len(text)

        return self._client.text_to_speech.stream(
            text=text,
            voice_id=self._voice_id,
            model_id=self._model_id,
            output_format=self._output_format,
            language_code=language_code,
        )
