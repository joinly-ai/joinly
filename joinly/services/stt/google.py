import asyncio
import io
import logging
import os
import wave
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Self

import google.generativeai as genai
from google.generativeai.types import GenerateContentResponse

from joinly.core import STT
from joinly.settings import get_settings
from joinly.types import (
    AudioFormat,
    IncompatibleAudioFormatError,
    SpeechWindow,
    TranscriptSegment,
)
from joinly.utils.audio import calculate_audio_duration, convert_audio_format
from joinly.utils.usage import add_usage

logger = logging.getLogger(__name__)


class GoogleSTT(STT):
    """Speech-to-Text (STT) service using Google's Gemini API."""

    def __init__(
        self,
        *,
        model_name: str = "gemini-2.5-flash",
        prompt: str = "Generate a transcript of the speech.",
    ) -> None:
        """Initialize the Google STT service.

        Args:
            model_name: The Gemini model to use for audio understanding.
            prompt: The prompt to send with the audio to request a transcript.
        """
        if os.getenv("GEMINI_API_KEY") is None and os.getenv("GOOGLE_API_KEY") is None:
            msg = "GEMINI_API_KEY or GOOGLE_API_KEY must be set in the environment."
            raise ValueError(msg)

        self._model_name = model_name
        self._prompt = prompt
        self._client: genai.GenerativeModel | None = None
        self._lock = asyncio.Lock()
        # Gemini downsamples audio to 16kHz for processing.
        # We will provide audio at this sample rate.
        self.audio_format = AudioFormat(sample_rate=16000, byte_depth=2)  # 16-bit PCM

    async def __aenter__(self) -> Self:
        """Configure the Gemini client."""
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        genai.configure(api_key=api_key)
        self._client = genai.GenerativeModel(self._model_name)
        logger.info("Initialized Google STT with model: %s", self._model_name)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources."""
        self._client = None

    async def stream(
        self, windows: AsyncIterator[SpeechWindow]
    ) -> AsyncIterator[TranscriptSegment]:
        """Transcribe an audio stream into a single text segment.

        Note: The Gemini audio understanding API is not a streaming API. This
        method buffers the entire audio stream for an utterance, then sends it
        for transcription at once.

        Args:
            windows: An asynchronous iterator of audio windows to transcribe.

        Yields:
            A single TranscriptSegment containing the full transcription.
        """
        if self._client is None:
            msg = "STT service is not initialized."
            raise RuntimeError(msg)

        # 1. Buffer the entire audio stream from the iterator.
        start_time: float | None = None
        end_time: float = 0.0
        audio_buffer = bytearray()
        speakers: defaultdict[str, float] = defaultdict(float)

        async for window in windows:
            if start_time is None:
                start_time = window.time_ns / 1e9

            # The TranscriptionController ensures the audio is in the format
            # specified by self.audio_format.
            audio_buffer.extend(window.data)

            duration = calculate_audio_duration(len(window.data), self.audio_format)
            end_time = (window.time_ns / 1e9) + duration
            if window.speaker:
                speakers[window.speaker] += duration

        if not audio_buffer:
            logger.warning("Received no audio data to transcribe.")
            return

        # 2. Convert the buffered PCM data to a WAV in-memory file.
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(self.audio_format.byte_depth)
            wf.setframerate(self.audio_format.sample_rate)
            wf.writeframes(audio_buffer)
        wav_buffer.seek(0)

        # 3. Send the audio to the Gemini API inline.
        async with self._lock:
            audio_duration_secs = calculate_audio_duration(
                len(audio_buffer), self.audio_format
            )
            logger.debug(
                "Sending %.2f seconds of audio to Google STT for transcription.",
                audio_duration_secs,
            )
            try:
                # CORRECTED PART: Create a dictionary instead of a Part object.
                audio_part = {
                    "inline_data": {
                        "mime_type": "audio/wav",
                        "data": wav_buffer.getvalue()
                    }
                }

                response: GenerateContentResponse = (
                    await self._client.generate_content_async(
                        contents=[self._prompt, audio_part]
                    )
                )
                transcribed_text = response.text.strip()

                add_usage(
                    service="google_stt",
                    usage={"seconds": audio_duration_secs},
                    meta={"model": self._model_name},
                )

                if transcribed_text:
                    # Determine the primary speaker for the segment
                    speaker = (
                        max(speakers.items(), key=lambda item: item[1])[0]
                        if speakers
                        else None
                    )
                    yield TranscriptSegment(
                        text=transcribed_text,
                        start=start_time or 0.0,
                        end=end_time,
                        speaker=speaker,
                    )
                else:
                    logger.info("Google STT returned an empty transcription.")

            except Exception as e:
                logger.exception("Error during Google STT transcription: %s", e)
                msg = f"Failed to transcribe audio with Google STT: {e}"
                raise RuntimeError(msg) from e