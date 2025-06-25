import asyncio
import contextlib
import logging
from collections import defaultdict
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
from joinly.utils.audio import calculate_audio_duration

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
        self._sent_seconds = 0.0
        self._queue: asyncio.Queue[TranscriptSegment | None] | None = None
        self._lock = asyncio.Lock()
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=2)

    async def __aenter__(self) -> Self:
        """Enter the context."""
        if await self._client.is_connected():
            msg = "Already started the audio stream."
            raise RuntimeError(msg)

        self._sent_seconds = 0.0
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
                        start=result.start - self._sent_seconds,
                        end=result.start - self._sent_seconds + result.duration,
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
        logger.info("Closing Deepgram STT service connection")
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

        stream_start: float | None = None
        speaker_windows: list[tuple[float, float, str | None]] = []

        async def _producer() -> None:
            """Producer coroutine to send audio data."""
            nonlocal stream_start
            async for window in windows:
                if stream_start is None:
                    stream_start = window.time_ns / 1e9
                start = window.time_ns / 1e9 - stream_start
                dur = calculate_audio_duration(len(window.data), self.audio_format)
                speaker_windows.append((start, start + dur, window.speaker))
                await self._client.send(window.data)
            await self._client.finalize()

        async with self._lock:
            while not self._queue.empty():
                _ = self._queue.get_nowait()
            producer = asyncio.create_task(_producer())

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

                    speakers: defaultdict[str | None, float] = defaultdict(float)
                    for start, end, speaker in speaker_windows:
                        speakers[speaker] += max(
                            0.0, min(end, segment.end) - max(start, segment.start)
                        )
                    speaker = max(speakers.items(), key=lambda item: item[1])[0]

                    yield TranscriptSegment(
                        text=segment.text,
                        start=segment.start + (stream_start or 0),
                        end=segment.end + (stream_start or 0),
                        speaker=speaker,
                    )
            finally:
                producer.cancel()
                self._sent_seconds += (
                    speaker_windows[-1][1] - speaker_windows[0][0]
                    if speaker_windows
                    else 0.0
                )
