import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Self

from joinly.core import STT, VAD, AudioReader, TranscriptionController
from joinly.types import AudioChunk, SpeechWindow, Transcript, TranscriptSegment
from joinly.utils.audio import calculate_audio_duration, convert_audio_format
from joinly.utils.clock import Clock
from joinly.utils.events import EventBus, EventType

logger = logging.getLogger(__name__)


class DefaultTranscriptionController(TranscriptionController):
    """A class to manage the transcription flow."""

    reader: AudioReader
    vad: VAD
    stt: STT

    def __init__(
        self,
        *,
        utterance_tail_seconds: float = 0.6,
        no_speech_event_delay: float = 0.4,
        max_stt_tasks: int = 5,
        window_queue_size: int = 100,
    ) -> None:
        """Initialize the TranscriptionController.

        Args:
            utterance_tail_seconds (float): The duration in seconds to wait after the
                last detected speech before considering the utterance complete
                (default is 0.6).
            no_speech_event_delay (float): The duration in seconds to wait before
                emitting a no-speech event (default is 0.4).
            max_stt_tasks (int): The maximum number of concurrent STT tasks
                (default is 5).
            window_queue_size (int): The maximum size of the window queue
                (default is 100).
        """
        self.utterance_tail_seconds = float(utterance_tail_seconds)
        self.no_speech_event_delay = float(no_speech_event_delay)
        self.max_stt_tasks = max_stt_tasks
        self.window_queue_size = window_queue_size
        self._vad_task: asyncio.Task | None = None
        self._window_queue: asyncio.Queue[SpeechWindow | None] | None = None
        self._stt_tasks: set[asyncio.Task] = set()
        self._no_speech_event = asyncio.Event()
        self._clock: Clock | None = None
        self._transcript: Transcript | None = None
        self._event_bus: EventBus | None = None

    @property
    def no_speech_event(self) -> asyncio.Event:
        """Get the event that is set when no speech is detected."""
        return self._no_speech_event

    async def __aenter__(self) -> Self:
        """Enter the transcription controller."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up the transcription controller."""
        await self.stop()

    async def start(
        self, clock: Clock, transcript: Transcript, event_bus: EventBus
    ) -> None:
        """Start the transcription controller with the given reader, vad, and stt.

        Args:
            clock (Clock): The clock to use for timing.
            transcript (Transcript): The transcript to use for storing segments.
            event_bus (EventBus): The event bus to publish events to.
        """
        if self._vad_task is not None:
            msg = "Transcription controller already started"
            raise RuntimeError(msg)

        self._no_speech_event.set()
        self._clock = clock
        self._transcript = transcript
        self._event_bus = event_bus
        self._vad_task = asyncio.create_task(self._vad_worker())

    async def stop(self) -> None:
        """Stop the transcription controller and clean up resources."""
        if self._vad_task is not None:
            self._vad_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._vad_task
            self._vad_task = None

        self._no_speech_event.clear()

        for task in list(self._stt_tasks):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._stt_tasks.clear()

        self._clock = None
        self._transcript = None
        self._event_bus = None
        self._window_queue = None

    def _notify(self, event_type: EventType) -> None:
        """Notify event bus of an event.

        Args:
            event_type (EventType): The event type to publish.
        """
        if self._event_bus is None:
            return

        self._event_bus.publish(event_type)

    async def _vad_worker(self) -> None:  # noqa: C901, PLR0915
        """Process audio data for vad and start utterance stt."""
        self._window_queue = None
        last_speech: int | None = None
        utterance_start: int | None = None
        dropped_windows: int = 0

        async def _chunk_iterator() -> AsyncIterator[AudioChunk]:
            """Yield audio chunks from the reader."""
            offset: int | None = None
            while True:
                chunk = await self.reader.read()
                if offset is None:
                    offset = chunk.time_ns
                now_ns = chunk.time_ns - offset
                if self._clock is not None:
                    self._clock.update(chunk.time_ns - offset)
                yield AudioChunk(
                    data=convert_audio_format(
                        chunk.data, self.reader.audio_format, self.vad.audio_format
                    ),
                    time_ns=now_ns,
                    speaker=chunk.speaker,
                )

        vad_stream = self.vad.stream(_chunk_iterator())
        async for window in vad_stream:
            if window.is_speech:
                last_speech = window.time_ns

            if window.is_speech and self._window_queue is None:
                # utterance start
                logger.debug("Utterance start: %.2fs", window.time_ns / 1e9)
                utterance_start = window.time_ns
                if len(self._stt_tasks) >= self.max_stt_tasks:
                    logger.warning(
                        "Maximum number of STT tasks reached (%d), dropping window",
                        self.max_stt_tasks,
                    )
                    continue

                self._window_queue = asyncio.Queue[SpeechWindow | None](
                    maxsize=self.window_queue_size
                )
                task = asyncio.create_task(self._stt_utterance(self._window_queue))
                task.add_done_callback(lambda t: self._stt_tasks.discard(t))
                self._stt_tasks.add(task)

            if (
                not window.is_speech
                and last_speech is not None
                and (window.time_ns - last_speech) / 1e9 >= self.utterance_tail_seconds
            ):
                # utterance end
                logger.debug("Utterance end: %.2fs", window.time_ns / 1e9)
                self._no_speech_event.set()
                last_speech = None
                utterance_start = None
                if self._window_queue is not None:
                    try:
                        self._window_queue.put_nowait(None)
                    except asyncio.QueueFull:
                        logger.warning(
                            "Frame queue is full, dropping middle frame for "
                            "utterance end"
                        )
                        self._window_queue.get_nowait()
                        self._window_queue.put_nowait(None)
                    self._window_queue = None

            if self._window_queue is not None:
                # in utterance
                if (
                    utterance_start is not None
                    and window.is_speech
                    and (window.time_ns - utterance_start) / 1e9
                    >= self.no_speech_event_delay
                ):
                    self._no_speech_event.clear()
                try:
                    self._window_queue.put_nowait(window)
                except asyncio.QueueFull:
                    dropped_windows += 1
                else:
                    if dropped_windows > 0:
                        logger.warning(
                            "Dropped %d audio windows due to full queue",
                            dropped_windows,
                        )
                    dropped_windows = 0

    async def _stt_utterance(self, queue: asyncio.Queue[SpeechWindow | None]) -> None:
        """Process speech windows for transcription."""
        if self._transcript is None:
            msg = "Transcription controller not active"
            raise RuntimeError(msg)
        start: float | None = None
        end: float | None = None
        end_ts: float | None = None

        async def _window_iterator() -> AsyncIterator[SpeechWindow]:
            """Yield windows from the window queue."""
            nonlocal start, end, end_ts
            while True:
                window = await queue.get()
                if window is None:
                    end_ts = time.monotonic()
                    break
                if start is None:
                    start = window.time_ns / 1e9
                end = window.time_ns / 1e9 + calculate_audio_duration(
                    len(window.data), self.vad.audio_format
                )
                yield SpeechWindow(
                    data=convert_audio_format(
                        window.data, self.vad.audio_format, self.stt.audio_format
                    ),
                    time_ns=window.time_ns,
                    is_speech=window.is_speech,
                    speaker=window.speaker,
                )

        seg_count = 0
        try:
            stt_stream = self.stt.stream(_window_iterator())
            async for s in stt_stream:
                start = start or float("-inf")
                end = end or float("inf")
                segment_start = min(max(s.start, start), end)
                segment_end = max(min(s.end, end), segment_start)
                segment = TranscriptSegment(
                    text=s.text,
                    start=segment_start,
                    end=segment_end,
                    speaker=s.speaker,
                )
                self._transcript.add_segment(segment)
                self._notify("segment")
                logger.debug(
                    "%s: %s (%.2fs-%.2fs)",
                    segment.speaker if segment.speaker else "Participant",
                    segment.text,
                    segment.start,
                    segment.end,
                )
                seg_count += 1
        except Exception:
            logger.exception("Error during STT processing")
            raise

        if seg_count > 0:
            if end_ts is not None:
                latency = time.monotonic() - end_ts
                log_level = logging.WARNING if latency > 0.3 else logging.DEBUG  # noqa: PLR2004
                logger.log(log_level, "STT utterance latency: %.3fs", latency)
            self._notify("utterance")
