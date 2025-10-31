import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Self

import google.generativeai as genai
from google.generativeai.types import GenerateContentResponse

from joinly.core import TTS
from joinly.settings import get_settings
from joinly.types import AudioFormat
from joinly.utils.usage import add_usage

logger = logging.getLogger(__name__)

# A mapping from BCP-47 language codes to available prebuilt voices.
# This helps select a reasonable default voice for a given language.
# Voice list from: https://ai.google.dev/gemini-api/docs/speech-generation#voice_options
DEFAULT_VOICES = {
    "en": "Zephyr",  # English - Upbeat
    "es": "Puck",  # Spanish - Upbeat (Note: Same voice name, model adapts)
    "de": "Puck",  # German - Upbeat
    "fr": "Puck",  # French - Upbeat
    "it": "Puck",  # Italian - Upbeat
    "pt": "Puck",  # Portuguese - Upbeat
    "ja": "Kore",  # Japanese - Firm
    "ko": "Kore",  # Korean - Firm
}


class GoogleTTS(TTS):
    """Text-to-Speech (TTS) service using Google's Gemini API."""

    def __init__(
        self,
        *,
        model_name: str = "gemini-2.5-flash-preview-tts",
        voice_name: str | None = None,
        sample_rate: int = 24000,
        chunk_size_bytes: int = 4096,
    ) -> None:
        """Initialize the Google TTS service.

        Args:
            model_name: The Gemini TTS model to use.
            voice_name: The prebuilt voice name to use (e.g., 'Kore', 'Puck').
                If None, a default is chosen based on the session language.
            sample_rate: The sample rate of the audio. Gemini TTS models output
                at 24000 Hz.
            chunk_size_bytes: The size of audio chunks to yield in bytes.
        """
        if os.getenv("GEMINI_API_KEY") is None and os.getenv("GOOGLE_API_KEY") is None:
            msg = "GEMINI_API_KEY or GOOGLE_API_KEY must be set in the environment."
            raise ValueError(msg)

        if sample_rate != 24000:
            logger.warning(
                "Google TTS currently only supports a 24000 Hz sample rate. "
                "Forcing sample_rate to 24000."
            )
            sample_rate = 24000

        self._model_name = model_name
        self._voice_name = voice_name or DEFAULT_VOICES.get(
            get_settings().language, "Puck"
        )
        self._chunk_size_bytes = chunk_size_bytes
        self._client: genai.GenerativeModel | None = None
        self._lock = asyncio.Lock()
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=2)  # 16-bit PCM

    async def __aenter__(self) -> Self:
        """Configure the Gemini client."""
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        genai.configure(api_key=api_key)
        self._client = genai.GenerativeModel(self._model_name)
        logger.info(
            "Initialized Google TTS with model: %s and voice: %s",
            self._model_name,
            self._voice_name,
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources."""
        self._client = None

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Convert text to speech and stream the audio data.

        Note: The Gemini TTS API is not a true streaming API. It generates the
        full audio clip at once. This method simulates a stream by chunking
        the complete audio data.

        Args:
            text: The text to convert to speech.

        Yields:
            bytes: The audio data chunks.
        """
        if self._client is None:
            msg = "TTS service is not initialized."
            raise RuntimeError(msg)

        async with self._lock:
            logger.debug("Generating audio for text: '%s'", text)

            # CORRECTED PART: Use dictionaries instead of genai.types classes
            speech_config = {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": self._voice_name
                    }
                }
            }
            generation_config = {
                "response_modalities": ["AUDIO"],
                "speech_config": speech_config,
            }

            try:
                # This is an async call but the underlying API call is blocking
                response: GenerateContentResponse = await self._client.generate_content_async(
                    contents=text, generation_config=generation_config
                )
                audio_data = response.candidates[0].content.parts[0].inline_data.data

                add_usage(
                    service="google_tts",
                    usage={"characters": len(text)},
                    meta={"model": self._model_name, "voice": self._voice_name},
                )

                logger.debug("Received %d bytes of audio data.", len(audio_data))

                # Chunk the received data to simulate a stream
                for i in range(0, len(audio_data), self._chunk_size_bytes):
                    yield audio_data[i : i + self._chunk_size_bytes]

            except Exception as e:
                logger.exception("Error during Google TTS generation: %s", e)
                msg = f"Failed to generate audio from Google TTS: {e}"
                raise RuntimeError(msg) from e