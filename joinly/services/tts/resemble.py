import asyncio
import logging
from collections.abc import AsyncIterator
from os import getenv

import aiohttp

from joinly.core import TTS
from joinly.types import AudioFormat
from joinly.utils.usage import add_usage

logger = logging.getLogger(__name__)


class ResembleTTS(TTS):
    """Resemble AI Text-to-Speech (TTS) service using HTTP streaming."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        api_key: str | None = None,
        voice_uuid: str | None = None,
        project_uuid: str | None = None,
        streaming_endpoint: str | None = None,
        sample_rate: int = 24000,
        precision: str = "PCM_16",
        use_hd: bool = False,
    ) -> None:
        """Initialize the Resemble TTS service."""
        self._api_key = api_key or getenv("RESEMBLE_AI_API_KEY")
        if not self._api_key:
            msg = "RESEMBLE_API_KEY must be set in environment or passed as arg"
            raise ValueError(msg)

        self._voice_uuid = voice_uuid or getenv("RESEMBLE_VOICE_UUID")
        if not self._voice_uuid:
            msg = "voice_uuid parameter or RESEMBLE_VOICE_UUID required"
            raise ValueError(msg)

        self._project_uuid = project_uuid or getenv("RESEMBLE_PROJECT_UUID")

        self._streaming_endpoint = streaming_endpoint or getenv(
            "RESEMBLE_STREAMING_ENDPOINT"
        )
        if not self._streaming_endpoint:
            msg = "streaming_endpoint parameter or RESEMBLE_STREAMING_ENDPOINT required"
            raise ValueError(msg)

        self._sample_rate = sample_rate
        self._precision = precision
        self._use_hd = use_hd
        self._lock = asyncio.Lock()

        byte_depth = 2 if precision == "PCM_16" else 1
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=byte_depth)

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Convert text to speech and stream the audio data using HTTP streaming."""
        async with self._lock:
            # Track usage (exclude None values from meta)
            meta: dict[str, str | int | float] | None = (
                {"voice": self._voice_uuid} if self._voice_uuid is not None else None
            )
            add_usage(
                service="resemble_tts",
                usage={"characters": len(text)},
                meta=meta,
            )

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

            timeout = aiohttp.ClientTimeout(total=25)

            # Safe for type checker: guaranteed non-None from __init__
            if self._streaming_endpoint is None:
                msg = "Streaming endpoint not configured"
                raise RuntimeError(msg)

            try:
                async with aiohttp.ClientSession() as session:  # noqa: SIM117
                    async with session.post(
                        self._streaming_endpoint,
                        headers=headers,
                        json=payload,
                        timeout=timeout,
                    ) as resp:
                        if resp.status != 200:  # noqa: PLR2004
                            body = await resp.text()
                            logger.error(
                                "Resemble TTS request failed: %s\nResponse: %s",
                                resp.status,
                                body,
                            )
                            msg = f"Resemble TTS request failed with {resp.status}"
                            raise RuntimeError(msg)  # noqa: TRY301

                        async for chunk in resp.content.iter_chunked(4096):
                            if chunk:
                                yield chunk

            except aiohttp.ClientError as e:
                msg = f"Resemble streaming request failed: {e}"
                logger.exception(msg)
                raise RuntimeError(msg) from e
            except Exception as e:
                msg = f"Unexpected error in Resemble TTS streaming: {e}"
                logger.exception(msg)
                raise RuntimeError(msg) from e
