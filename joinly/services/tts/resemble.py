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

    def __init__(
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
        """Initialize the Resemble TTS service.

        Args:
            api_key: The Resemble AI API key.
            voice_uuid: The Resemble voice UUID to use.
            project_uuid: The Resemble project UUID. # not needed for all endpoints
            streaming_endpoint: (in the env file) https://f.cluster.resemble.ai/stream
            sample_rate: The sample rate of the audio (default is 24000).
            precision: The audio precision format (default is "PCM_16").
            use_hd: Enable high-definition audio synthesis (default is False).
        """

        # fetch the key, ID,  end point 
        self._api_key = api_key or getenv("RESEMBLE_AI_API_KEY")
        if not self._api_key:
            msg = "RESEMBLE_API_KEY must be set in environment or passed as arg"
            raise ValueError(msg)

        self._voice_uuid = voice_uuid or getenv("RESEMBLE_VOICE_UUID")
        if not self._voice_uuid:
            msg = "voice_uuid parameter or RESEMBLE_VOICE_UUID required"
            raise ValueError(msg)
            
        self._project_uuid = project_uuid or getenv("RESEMBLE_PROJECT_UUID")
        # project_uuid is optional - some endpoints work without it

        self._streaming_endpoint = (
            streaming_endpoint or getenv("RESEMBLE_STREAMING_ENDPOINT")
        )
        if not self._streaming_endpoint:
            msg = (
                "streaming_endpoint parameter or "
                "RESEMBLE_STREAMING_ENDPOINT required"
            ) 
            raise ValueError(msg)

        self._sample_rate = sample_rate
        self._precision = precision
        self._use_hd = use_hd
        self._lock = asyncio.Lock()

        # Set audio format based on precision
        byte_depth = 2 if precision == "PCM_16" else 1
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=byte_depth)

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Convert text to speech and stream the audio data using HTTP streaming.

        Args:
            text: The text to convert to speech.

        Returns:
            AsyncIterator[bytes]: An asynchronous iterator that yields audio chunks.
        """
        async with self._lock:
            # Track usage
            add_usage(
                service="resemble_tts",
                usage={"characters": len(text)},
                meta={"voice": self._voice_uuid},
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
            
            # Add project_uuid only if available
            if self._project_uuid:
                payload["project_uuid"] = self._project_uuid

            try:
                async with aiohttp.ClientSession() as session, session.post(
                    self._streaming_endpoint, 
                    headers=headers, 
                    json=payload,
                    timeout=30
                ) as resp:
                    resp.raise_for_status()
                    
                    # Stream the response chunks
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
