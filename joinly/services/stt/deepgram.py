import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Self

from deepgram import (
    AsyncListenWebSocketClient,
    DeepgramClient,
    DeepgramClientOptions,
    LiveOptions,
    LiveResultResponse,
    LiveTranscriptionEvents,
)

from joinly.core import STT
from joinly.settings import get_settings
from joinly.types import (
    AudioFormat,
    SpeechWindow,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)


class DeepgramSTT(STT):
    """A class to transcribe audio using Deepgram."""

    def __init__(
        self,
        *,
        model_name: str = "nova-3-general",
        sample_rate: int = 16000,
        hotwords: list[str] | None = None,
        stream_idle_timeout: float = 2.0,
    ) -> None:
        """Initialize the DeepgramSTT.

        Args:
            model_name: The Deepgram model to use (default is "nova-3-general").
            sample_rate: The sample rate of the audio (default is 16000).
            hotwords: A list of hotwords to improve transcription accuracy.
            stream_idle_timeout: The duration to wait after finalizing the stream before
                closing it (default is 2.0 seconds). Normally, this should never
                trigger as the stream is finalized.
        """
        config = DeepgramClientOptions(options={"keep_alive": True})
        dg = DeepgramClient(config=config)
        self._client: AsyncListenWebSocketClient = dg.listen.asyncwebsocket.v("1")  # type: ignore[attr-type]
        self._live_options = LiveOptions(
            model=model_name,
            encoding="linear16",
            sample_rate=sample_rate,
            language="en",
            channels=1,
            endpointing=False,
            interim_results=False,
            punctuate=True,
            profanity_filter=True,
            vad_events=False,
            keyterm=(
                (hotwords or []) + [get_settings().name]
                if model_name.startswith("nova-3")
                else None
            ),
        )
        self._stream_idle_timeout = stream_idle_timeout
        self._queue: asyncio.Queue[TranscriptSegment | None] | None = None
        self._lock = asyncio.Lock()
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=2)

    async def __aenter__(self) -> Self:
        """Enter the context."""
        if await self._client.is_connected():
            msg = "Already started the audio stream."
            raise RuntimeError(msg)

        self._queue = asyncio.Queue[TranscriptSegment | None]()

        async def on_result(
            _client: AsyncListenWebSocketClient,
            result: LiveResultResponse,
            **_kwargs: object,
        ) -> None:
            """Handle incoming messages from the WebSocket."""
            logger.debug("Received message: %s", result)
            if result.channel.alternatives:
                transcript = result.channel.alternatives[0].transcript
                if transcript:
                    segment = TranscriptSegment(
                        text=transcript,
                        start=0,
                        end=result.duration,
                    )
                    await self._queue.put(segment)  # type: ignore[attr-defined]
                if result.from_finalize:
                    await self._queue.put(None)  # type: ignore[attr-defined]

        self._client.on(LiveTranscriptionEvents.Transcript, on_result)  # type: ignore[arg-type]

        logger.info(
            "Connecting to Deepgram STT service with model: %s",
            self._live_options.model,
        )
        await self._client.start(self._live_options)
        logger.info("Connected to Deepgram STT service")

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the context."""
        logger.info("Closing Deepgram TTS service connection")
        await self._client.finish()
        self._queue = None

    async def stream(
        self, windows: AsyncIterator[SpeechWindow]
    ) -> AsyncIterator[TranscriptSegment]:
        """Stream audio windows and yield transcribed segments.

        Args:
            windows: An AsyncIterator of SpeechWindow objects.

        Yields:
            TranscriptSegment: The transcribed segments.
        """
        if self._queue is None or not await self._client.is_connected():
            msg = "STT service is not started."
            raise RuntimeError(msg)

        start: float | None = None
        end: float | None = None

        async def _producer() -> None:
            """Producer coroutine to send audio data."""
            nonlocal start, end
            async for window in windows:
                if start is None:
                    start = window.start
                end = window.start
                await self._client.send(window.data)
            await self._client.finalize()

        producer = asyncio.create_task(_producer())

        async with self._lock:
            try:
                while True:
                    cm = (
                        asyncio.timeout(self._stream_idle_timeout)
                        if producer.done()
                        else contextlib.nullcontext()
                    )
                    try:
                        async with cm:
                            segment = await self._queue.get()
                    except TimeoutError:
                        logger.warning(
                            "Stream idle timeout (%.2fs) reached before reaching "
                            "finalization. Terminating stream.",
                            self._stream_idle_timeout,
                        )
                        break
                    if segment is None:
                        break

                    yield TranscriptSegment(
                        text=segment.text,
                        start=start or 0,
                        end=min(end or float("inf"), (start or 0) + segment.end),
                    )
                    start = (start or 0) + segment.end
            finally:
                producer.cancel()
                try:
                    while True:
                        self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
