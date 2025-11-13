import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Self

from google import genai
from google.genai import types

from joinly.core import TTS
from joinly.settings import get_settings
from joinly.types import AudioFormat
from joinly.utils.usage import add_usage

logger = logging.getLogger(__name__)

# A mapping from BCP-47 language codes to available prebuilt voices.
# This helps select a reasonable default voice for a given language.
# Voice list from: https://ai.google.dev/gemini-api/docs/speech-generation#voice_options
DEFAULT_VOICES = {
    "en": "Zephyr",  # English - Bright
    "es": "Puck",  # Spanish - Upbeat
    "de": "Puck",  # German - Upbeat
    "fr": "Puck",  # French - Upbeat
    "it": "Puck",  # Italian - Upbeat
    "pt": "Puck",  # Portuguese - Upbeat
    "ja": "Kore",  # Japanese - Firm
    "ko": "Kore",  # Korean - Firm
    "zh": "Kore",  # Chinese - Firm
    "hi": "Puck",  # Hindi - Upbeat
    "ar": "Puck",  # Arabic - Upbeat
}

# Sample rate constant
REQUIRED_SAMPLE_RATE = 24000


class GoogleTTS(TTS):
    """Text-to-Speech (TTS) service using Gemini speech generation API."""

    def __init__(
        self,
        *,
        model_name: str = "gemini-2.5-flash-preview-tts",
        voice_name: str | None = None,
        sample_rate: int = REQUIRED_SAMPLE_RATE,
        chunk_size_bytes: int = 4096,
    ) -> None:
        """Initialize the Gemini TTS service.

        Args:
            model_name: The Gemini TTS model to use (default is flash preview).
            voice_name: The prebuilt voice name to use (e.g., 'Kore', 'Puck', 'Zephyr').
                If None, a default is chosen based on the session language.
                See https://ai.google.dev/gemini-api/docs/speech-generation#voice_options
                for all 30 available voices.
            sample_rate: The sample rate of the audio. Gemini TTS outputs at 24kHz.
            chunk_size_bytes: The size of audio chunks to yield in bytes.
        """
        if os.getenv("GEMINI_API_KEY") is None and os.getenv("GOOGLE_API_KEY") is None:
            msg = "GEMINI_API_KEY or GOOGLE_API_KEY must be set in the environment."
            raise ValueError(msg)

        if sample_rate != REQUIRED_SAMPLE_RATE:
            logger.warning(
                "Gemini TTS outputs at %d Hz. Forcing sample_rate to %d.",
                REQUIRED_SAMPLE_RATE,
                REQUIRED_SAMPLE_RATE,
            )
            sample_rate = REQUIRED_SAMPLE_RATE

        self._model = model_name
        self._voice_name = voice_name or DEFAULT_VOICES.get(
            get_settings().language, "Puck"
        )
        self._chunk_size_bytes = chunk_size_bytes
        self._client: genai.Client | None = None
        self._lock = asyncio.Lock()

        # Gemini TTS outputs 24kHz, 16-bit PCM audio
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=2)

    async def __aenter__(self) -> Self:
        """Initialize the Gemini client."""
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self._client = genai.Client(api_key=api_key)

        logger.info(
            "Initialized Gemini TTS with model: %s and voice: %s",
            self._model,
            self._voice_name,
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources."""
        self._client = None

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Convert text to speech and stream the audio data.

        Note: The Gemini TTS API generates the full audio at once.
        This method chunks the audio to simulate streaming.

        Args:
            text: The text to convert to speech.

        Yields:
            bytes: The audio data chunks (PCM format, 24kHz, 16-bit).
        """
        if self._client is None:
            msg = "TTS service is not initialized."
            raise RuntimeError(msg)

        async with self._lock:
            logger.debug("Generating audio for text: '%s'", text)

            try:
                # Configure speech generation
                config = types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=self._voice_name,
                            )
                        )
                    ),
                )

                # Generate audio
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=text,
                    config=config,
                )

                # Extract audio data
                def _validate_response() -> None:
                    """Validate that response contains audio data."""
                    if (
                        not response.candidates
                        or not response.candidates[0].content
                        or not response.candidates[0].content.parts
                        or not response.candidates[0].content.parts[0].inline_data
                    ):
                        msg = "No audio data in response"
                        raise RuntimeError(msg)  # noqa: TRY301

                _validate_response()

                # Type narrowing: validation ensures these are not None
                if not response.candidates:
                    msg = "No candidates after validation"
                    raise RuntimeError(msg)  # noqa: TRY301

                candidate = response.candidates[0]
                if not candidate.content or not candidate.content.parts:
                    msg = "No content or parts after validation"
                    raise RuntimeError(msg)  # noqa: TRY301

                part = candidate.content.parts[0]
                if not part.inline_data or not part.inline_data.data:
                    msg = "No inline data after validation"
                    raise RuntimeError(msg)  # noqa: TRY301

                audio_data = part.inline_data.data

                if not audio_data:
                    logger.warning("Received empty audio data from Gemini TTS.")
                    return

                # Track usage
                add_usage(
                    service="gemini_tts",
                    usage={"characters": len(text)},
                    meta={"model": self._model, "voice": self._voice_name},
                )

                logger.debug("Generated %d bytes of audio data.", len(audio_data))

                # Chunk the audio data for streaming
                for i in range(0, len(audio_data), self._chunk_size_bytes):
                    yield audio_data[i : i + self._chunk_size_bytes]

            except Exception as e:
                logger.exception("Error during Gemini TTS generation")
                msg = f"Failed to generate audio from Gemini TTS: {e}"
                raise RuntimeError(msg) from e
