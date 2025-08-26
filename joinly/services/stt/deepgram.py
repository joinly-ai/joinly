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
from joinly.utils.usage import add_usage

logger = logging.getLogger(__name__)


class DeepgramSTT(STT):
    """A class to transcribe audio using Deepgram."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        model_name: str | None = None,
        sample_rate: int = 16000,
        hotwords: list[str] | None = None,
        finalize_silence: float = 0.4,
        padding_silence: float = 0.5,
        stream_idle_timeout: float = 1.0,
        mip_opt_out: bool = True,
    ) -> None:
        """Initialize the DeepgramSTT.

        Args:
            model_name: The Deepgram model to use (default is "nova-3-general" for
                English and "nova-2-general" otherwise).
            sample_rate: The sample rate of the audio (default is 16000).
            hotwords: A list of hotwords to improve transcription accuracy.
            finalize_silence: The duration of silence to wait before finalizing the
                stream (default is 0.4 seconds).
            padding_silence: The duration of silence to pad at the start of each audio
                window (default is 0.2 seconds).
            stream_idle_timeout: The duration to wait after finalizing the stream before
                closing it (default is 1.0 seconds). Normally, this should never
                trigger as the stream is finalized.
            mip_opt_out: Whether to opt out of the model improvement program
                (default is True). See more at https://developers.deepgram.com/docs/the-deepgram-model-improvement-partnership-program.
        """
        config = DeepgramClientOptions(options={"keep_alive": True})
        dg = DeepgramClient(config=config)
        self._client: AsyncListenWebSocketClient = dg.listen.asyncwebsocket.v("1")  # type: ignore[attr-type]
        self.model_name = model_name or (
            "nova-3-general" if get_settings().language == "en" else "nova-2-general"
        )
        self.finalize_silence = finalize_silence
        self._live_options = LiveOptions(
            model=self.model_name,
            encoding="linear16",
            sample_rate=sample_rate,
            language=get_settings().language,
            channels=1,
            endpointing=False,
            interim_results=False,
            punctuate=True,
            profanity_filter=True,
            vad_events=False,
            keyterm=(
                (hotwords or []) + [get_settings().name]
                if self.model_name.startswith("nova-3")
                else None
            ),
        )
        self._mip_opt_out = bool(mip_opt_out)
        self._stream_idle_timeout = stream_idle_timeout
        self._sent_seconds = 0.0
        self._queue: asyncio.Queue[TranscriptSegment | None] | None = None
        self._lock = asyncio.Lock()
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=2)
        self._padding_silence = b"\x00" * (
            int(padding_silence * self.audio_format.sample_rate)
            * self.audio_format.byte_depth
        )
        self._padding_silence_dur = padding_silence

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
        await self._client.start(
            self._live_options, addons={"mip_opt_out": self._mip_opt_out}
        )
        if not await self._client.is_connected():
            msg = "Failed to connect to Deepgram STT service."
            logger.error(msg)
            raise RuntimeError(msg)
        logger.debug("Connected to Deepgram STT service")

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the context."""
        logger.debug("Closing Deepgram STT service connection")
        await self._client.finish()
        self._queue = None

    async def stream(  # noqa: C901, PLR0915
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
        stream_end: float | None = None
        speaker_windows: list[tuple[float, float, str]] = []

        async def _producer() -> None:
            """Producer coroutine to send audio data."""
            nonlocal stream_start, stream_end
            if self._padding_silence:
                self._sent_seconds += self._padding_silence_dur
                await self._client.send(self._padding_silence)
                add_usage(
                    service="deepgram_stt",
                    usage={"minutes": self._padding_silence_dur / 60},
                    meta={"model": self.model_name, "mip_opt_out": self._mip_opt_out},
                )
            async for window in windows:
                if stream_start is None:
                    stream_start = window.time_ns / 1e9
                cur = window.time_ns / 1e9
                dur = calculate_audio_duration(len(window.data), self.audio_format)
                stream_end = cur + dur
                if window.speaker is not None:
                    speaker_windows.append(
                        (cur - stream_start, cur - stream_start + dur, window.speaker)
                    )
                await self._client.send(window.data)
                add_usage(
                    service="deepgram_stt",
                    usage={"minutes": dur / 60},
                    meta={"model": self.model_name, "mip_opt_out": self._mip_opt_out},
                )
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

                    speakers: defaultdict[str, float] = defaultdict(float)
                    for start, end, speaker in speaker_windows:
                        speakers[speaker] += max(
                            0.0, min(end, segment.end) - max(start, segment.start)
                        )
                    speaker, speaker_time = max(
                        speakers.items(),
                        key=lambda x: x[1],
                        default=(None, 0),
                    )
                    if speaker_time < 0.1 * (segment.end - segment.start):
                        speaker = None

                    yield TranscriptSegment(
                        text=segment.text,
                        start=segment.start + (stream_start or 0),
                        end=segment.end + (stream_start or 0),
                        speaker=speaker,
                    )
            finally:
                producer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await producer
                self._sent_seconds += (stream_end or 0) - (stream_start or 0)
