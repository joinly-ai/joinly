import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Self

from deepgram import (
    AsyncSpeakWebSocketClient,
    DeepgramClient,
    DeepgramClientOptions,
    SpeakWebSocketEvents,
    SpeakWSOptions,
)

from joinly.core import TTS
from joinly.settings import get_settings
from joinly.types import AudioFormat
from joinly.utils.usage import add_usage

logger = logging.getLogger(__name__)


class DeepgramTTS(TTS):
    """Text-to-Speech (TTS) service for converting text to speech."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        sample_rate: int = 24000,
        mip_opt_out: bool = True,
    ) -> None:
        """Initialize the TTS service.

        Args:
            model_name: The Deepgram TTS model to use (default is "aura-2-andromeda-en"
                for English and "aura-2-estrella-es" for Spanish).
            sample_rate: The sample rate of the audio (default is 24000).
            mip_opt_out: Whether to opt out of the model improvement program
                (default is True). See more at https://developers.deepgram.com/docs/the-deepgram-model-improvement-partnership-program.
        """
        config = DeepgramClientOptions(
            options={
                "keep_alive": True,
                "speaker_playback": False,
            }
        )
        dg = DeepgramClient(config=config)
        self._client: AsyncSpeakWebSocketClient = dg.speak.asyncwebsocket.v("1")
        if model_name is None and get_settings().language not in ["en", "es"]:
            logger.warning(
                "Unsupported language %s for Deepgram TTS, falling back to English.",
                get_settings().language,
            )
        self.model_name = model_name or (
            "aura-2-estrella-es"
            if get_settings().language == "es"
            else "aura-2-andromeda-en"
        )
        self._speak_options = SpeakWSOptions(
            model=self.model_name,
            encoding="linear16",
            sample_rate=sample_rate,
        )
        self._mip_opt_out = bool(mip_opt_out)
        self._queue: asyncio.Queue[bytes | None] | None = None
        self._lock = asyncio.Lock()
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=2)

    async def __aenter__(self) -> Self:
        """Enter the asynchronous context manager."""
        if await self._client.is_connected():
            msg = "Already started the audio stream."
            raise RuntimeError(msg)

        self._queue = asyncio.Queue[bytes | None]()

        async def on_data(
            _client: AsyncSpeakWebSocketClient, data: bytes, **_kwargs: object
        ) -> None:
            """Handle binary data received from the WebSocket."""
            logger.debug("Received binary data of size: %s", len(data))
            await self._queue.put(data)  # type: ignore[attr-defined]

        async def on_flushed(
            _client: AsyncSpeakWebSocketClient, **_kwargs: object
        ) -> None:
            """Handle flushed event from the WebSocket."""
            logger.debug("Flushed event received.")
            await self._queue.put(None)  # type: ignore[attr-defined]

        self._client.on(SpeakWebSocketEvents.AudioData, on_data)  # type: ignore[arg-type]
        self._client.on(SpeakWebSocketEvents.Flushed, on_flushed)  # type: ignore[arg-type]

        logger.info(
            "Connecting to Deepgram TTS service with model: %s",
            self._speak_options.model,
        )
        await self._client.start(
            self._speak_options, addons={"mip_opt_out": self._mip_opt_out}
        )
        if not await self._client.is_connected():
            msg = "Failed to connect to Deepgram TTS service."
            logger.error(msg)
            raise RuntimeError(msg)
        logger.debug("Connected to Deepgram TTS service")

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the asynchronous context manager."""
        logger.debug("Closing Deepgram TTS service connection")
        await self._client.finish()
        self._queue = None

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Convert text to speech and stream the audio data.

        Args:
            text: The text to convert to speech.

        Yields:
            bytes: The audio data.
        """
        if self._queue is None or not await self._client.is_connected():
            msg = "TTS service is not started."
            raise RuntimeError(msg)

        async with self._lock:
            # drain the queue to ensure no old data is left
            while not self._queue.empty():
                _ = self._queue.get_nowait()

            try:
                await self._client.send_text(text)
                await self._client.flush()
                add_usage(
                    service="deepgram_tts",
                    usage={"characters": len(text)},
                    meta={"model": self.model_name, "mip_opt_out": self._mip_opt_out},
                )

                while (chunk := await self._queue.get()) is not None:
                    yield chunk
            finally:
                await self._client.clear()
