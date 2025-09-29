import asyncio
import logging
import os
from collections.abc import AsyncIterator

import aiohttp

from joinly.core import TTS
from joinly.types import AudioFormat
from joinly.utils.audio import calculate_audio_duration
from joinly.utils.usage import add_usage

logger = logging.getLogger(__name__)


class ResembleTTS(TTS):
    """Resemble AI Text-to-Speech (TTS) service using HTTP streaming."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        voice_uuid: str | None = None,
        project_uuid: str | None = None,
        streaming_endpoint: str | None = None,
        sample_rate: int = 24000,
        precision: str = "PCM_16",
        use_hd: bool = False,
    ) -> None:
        """Initialize the Resemble TTS service."""
        self._api_key = os.getenv("RESEMBLE_API_KEY")
        if not self._api_key:
            msg = "RESEMBLE_API_KEY must be set in the environment"
            raise ValueError(msg)

        self._voice_uuid = voice_uuid or "a72d9fca"
        self._project_uuid = project_uuid or os.getenv("RESEMBLE_PROJECT_UUID")
        self._streaming_endpoint = streaming_endpoint or os.getenv(
            "RESEMBLE_STREAMING_ENDPOINT", "https://f.cluster.resemble.ai/stream"
        )

        self._sample_rate = sample_rate
        self._precision = precision
        self._use_hd = use_hd
        self._lock = asyncio.Lock()

        byte_depth = 2 if precision == "PCM_16" else 4
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=byte_depth)

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Convert text to speech and stream the audio data using HTTP streaming."""
        async with self._lock:
            headers = {
                "Authorization": f"Token {self._api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "voice_uuid": self._voice_uuid,
                "data": text,
                "sample_rate": self._sample_rate,
                "precision": self._precision,
                "use_hd": self._use_hd,
            }
            if self._project_uuid:
                payload["project_uuid"] = self._project_uuid

            received_bytes = 0
            try:
                async with (
                    aiohttp.ClientSession() as session,
                    session.post(
                        self._streaming_endpoint,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(connect=4),
                    ) as resp,
                ):
                    if resp.status != 200:  # noqa: PLR2004
                        body = await resp.text()
                        logger.error(
                            "Resemble TTS request failed with %d: %s",
                            resp.status,
                            body,
                        )
                        msg = f"Resemble TTS request failed with {resp.status}"
                        raise RuntimeError(msg)

                    data_start = False
                    buf = bytearray()
                    async for chunk in resp.content.iter_any():
                        # skip the WAV header
                        if not data_start:
                            buf.extend(chunk)
                            i = buf.find(b"data")
                            if i == -1 or len(buf) < i + 8:
                                continue
                            chunk = bytes(buf[i + 8 :])  # noqa: PLW2901
                            buf.clear()
                            data_start = True
                            if not chunk:
                                continue
                        received_bytes += len(chunk)
                        yield chunk

            except aiohttp.ClientError as e:
                msg = f"Resemble streaming request failed: {e}"
                logger.exception(msg)
                raise RuntimeError(msg) from e

            finally:
                add_usage(
                    service="resemble_tts",
                    usage={
                        "minutes": calculate_audio_duration(
                            received_bytes, self.audio_format
                        )
                        / 60
                    },
                    meta={"voice": self._voice_uuid, "hd": self._use_hd},
                )
