import asyncio
import logging
import os
from collections.abc import AsyncIterator

import aiohttp

from joinly.core import TTS
from joinly.settings import get_settings
from joinly.types import AudioFormat
from joinly.utils.usage import add_usage

logger = logging.getLogger(__name__)

_MINIMAX_TTS_URL = "https://api.minimax.io/v1/t2a_v2"

# Default voices per language (BCP-47 → MiniMax voice ID).
# Full list of English voices: English_Graceful_Lady, English_Insightful_Speaker,
#   English_radiant_girl, English_Persuasive_Man, English_Lucky_Robot
# Multilingual voices: Wise_Woman, cute_boy, lovely_girl, Friendly_Person,
#   Inspirational_girl, Deep_Voice_Man, sweet_girl
DEFAULT_VOICES: dict[str, str] = {
    "en": "English_Graceful_Lady",
    "zh": "Wise_Woman",
    "de": "Friendly_Person",
    "fr": "Friendly_Person",
    "es": "Friendly_Person",
    "ja": "Wise_Woman",
    "ko": "Wise_Woman",
}


class MinimaxTTS(TTS):
    """Text-to-Speech (TTS) service using the MiniMax Cloud TTS API.

    Uses the MiniMax ``t2a_v2`` endpoint with PCM output so the audio can be
    consumed directly by joinly's audio pipeline without additional decoding.

    Environment variables:
        MINIMAX_API_KEY: Required. Your MiniMax API key.

    See https://www.minimax.io/audio/text-to-speech for voice options.
    """

    def __init__(
        self,
        *,
        model: str = "speech-02-hd",
        voice_id: str | None = None,
        sample_rate: int = 32000,
        speed: float = 1.0,
        vol: float = 1.0,
        pitch: int = 0,
        chunk_size_bytes: int = 4096,
    ) -> None:
        """Initialize the MiniMax TTS service.

        Args:
            model: The MiniMax TTS model to use. Options: ``speech-02-hd``
                (default, higher quality) or ``speech-02-turbo`` (faster).
            voice_id: The MiniMax voice ID. If *None*, a language-appropriate
                default is chosen automatically.
            sample_rate: PCM sample rate in Hz (default 32000).
            speed: Speech speed multiplier in the range [0.5, 2.0] (default 1.0).
            vol: Volume multiplier in the range [0.1, 10.0] (default 1.0).
            pitch: Pitch adjustment in the range [-12, 12] semitones (default 0).
            chunk_size_bytes: Size of audio chunks yielded during streaming
                (default 4096 bytes).
        """
        self._api_key = os.getenv("MINIMAX_API_KEY")
        if not self._api_key:
            msg = "MINIMAX_API_KEY must be set in the environment."
            raise ValueError(msg)

        self._model = model
        self._voice_id = voice_id or DEFAULT_VOICES.get(
            get_settings().language, "English_Graceful_Lady"
        )
        self._sample_rate = sample_rate
        self._speed = speed
        self._vol = vol
        self._pitch = pitch
        self._chunk_size_bytes = chunk_size_bytes
        self._lock = asyncio.Lock()

        # PCM 16-bit audio
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=2)

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Convert text to speech and stream the raw PCM audio.

        Args:
            text: The text to synthesize.

        Yields:
            bytes: Raw PCM audio data chunks (16-bit, mono).
        """
        async with self._lock:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self._model,
                "text": text,
                "stream": False,
                "voice_setting": {
                    "voice_id": self._voice_id,
                    "speed": self._speed,
                    "vol": self._vol,
                    "pitch": self._pitch,
                },
                "audio_setting": {
                    "sample_rate": self._sample_rate,
                    "bitrate": 128000,
                    "format": "pcm",
                    "channel": 1,
                },
            }

            try:
                async with (
                    aiohttp.ClientSession() as session,
                    session.post(
                        _MINIMAX_TTS_URL,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=30, connect=5),
                    ) as resp,
                ):
                    if resp.status != 200:  # noqa: PLR2004
                        body = await resp.text()
                        logger.error(
                            "MiniMax TTS request failed with %d: %s",
                            resp.status,
                            body,
                        )
                        msg = f"MiniMax TTS request failed with status {resp.status}"
                        raise RuntimeError(msg)

                    data = await resp.json()

                    base_resp = data.get("base_resp", {})
                    status_code = base_resp.get("status_code", 0)
                    if status_code != 0:
                        status_msg = base_resp.get("status_msg", "unknown error")
                        logger.error(
                            "MiniMax TTS API error %d: %s",
                            status_code,
                            status_msg,
                        )
                        msg = f"MiniMax TTS API error {status_code}: {status_msg}"
                        raise RuntimeError(msg)

                    hex_audio = data.get("data", {}).get("audio", "")
                    if not hex_audio:
                        logger.warning("MiniMax TTS returned empty audio data.")
                        return

                    audio_bytes = bytes.fromhex(hex_audio)

                    add_usage(
                        service="minimax_tts",
                        usage={"characters": len(text)},
                        meta={"model": self._model, "voice": self._voice_id},
                    )

                    logger.debug(
                        "MiniMax TTS generated %d bytes of PCM audio.", len(audio_bytes)
                    )

                    for i in range(0, len(audio_bytes), self._chunk_size_bytes):
                        yield audio_bytes[i : i + self._chunk_size_bytes]

            except aiohttp.ClientError as e:
                msg = f"MiniMax TTS HTTP request failed: {e}"
                logger.exception(msg)
                raise RuntimeError(msg) from e
