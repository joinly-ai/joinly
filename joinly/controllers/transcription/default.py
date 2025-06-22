import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Self

from joinly.core import STT, VAD, AudioReader, TranscriptionController
from joinly.types import AudioChunk, SpeechWindow, Transcript
from joinly.utils.audio import convert_audio_format

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
        max_stt_tasks: int = 5,
        window_queue_size: int = 100,
    ) -> None:
        """Initialize the TranscriptionController.

        Args:
            utterance_tail_seconds (float): The duration in seconds to wait after the
                last detected speech before considering the utterance complete
                (default is 0.6).
            max_stt_tasks (int): The maximum number of concurrent STT tasks
                (default is 5).
            window_queue_size (int): The maximum size of the window queue
                (default is 100).
        """
        self.utterance_tail_seconds = utterance_tail_seconds
        self.max_stt_tasks = max_stt_tasks
        self.window_queue_size = window_queue_size
        self._transcript = Transcript()
        self._vad_task: asyncio.Task | None = None
        self._window_queue: asyncio.Queue[SpeechWindow | None] | None = None
        self._stt_tasks: set[asyncio.Task] = set()
        self._no_speech_event = asyncio.Event()
        self._listeners: set[Callable[[str], Coroutine[None, None, None]]] = set()
        self._time_ns: int = 0

    @property
    def transcript(self) -> Transcript:
        """Get the current transcript."""
        return self._transcript

    @property
    def transcript_seconds(self) -> float:
        """Get the current transcript duration in seconds."""
        return self._time_ns / 1e9

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

    async def start(self) -> None:
        """Start the transcription controller with the given reader, vad, and stt."""
        if self._vad_task is not None:
            msg = "Transcription controller already started"
            raise RuntimeError(msg)

        self._no_speech_event.set()
        self._time_ns = 0
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

        self._window_queue = None

    def add_listener(
        self, listener: Callable[[str], Coroutine[None, None, None]]
    ) -> Callable[[], None]:
        """Add a listener."""
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _notify(self, event: str) -> None:
        """Notify all listeners in a fire and forget manner.

        Args:
            event (str): The event to notify listeners about.

        TODO: improve event handling
        """
        for listener in self._listeners:
            asyncio.create_task(listener(event))  # noqa: RUF006

    async def _vad_worker(self) -> None:  # noqa: C901
        """Process audio data for vad and start utterance stt."""
        self._window_queue = None
        last_speech: int | None = None
        dropped_windows: int = 0

        async def _chunk_iterator() -> AsyncIterator[AudioChunk]:
            """Yield audio chunks from the reader."""
            offset: int | None = None
            while True:
                chunk = await self.reader.read()
                if offset is None:
                    offset = chunk.time_ns
                self._time_ns = chunk.time_ns - offset
                yield AudioChunk(
                    data=convert_audio_format(
                        chunk.data, self.reader.audio_format, self.vad.audio_format
                    ),
                    time_ns=self._time_ns,
                    speaker=chunk.speaker,
                )

        vad_stream = self.vad.stream(_chunk_iterator())
        async for window in vad_stream:
            if window.is_speech:
                last_speech = window.time_ns

            if window.is_speech and self._window_queue is None:
                # utterance start
                logger.info("Utterance start: %.2fs", window.time_ns / 1e9)
                self._no_speech_event.clear()
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
                logger.info("Utterance end: %.2fs", window.time_ns / 1e9)
                self._no_speech_event.set()
                last_speech = None
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
                try:
                    self._window_queue.put_nowait(window)
                except asyncio.QueueFull:
                    dropped_windows += 1
                    if dropped_windows == 1:
                        logger.info("Window queue is full, dropping audio windows")
                else:
                    if dropped_windows > 0:
                        logger.warning(
                            "Dropped %d audio windows due to full queue",
                            dropped_windows,
                        )
                    dropped_windows = 0

    async def _stt_utterance(self, queue: asyncio.Queue[SpeechWindow | None]) -> None:
        """Process speech windows for transcription."""
        end_ts: float | None = None

        async def _window_iterator() -> AsyncIterator[SpeechWindow]:
            """Yield windows from the window queue."""
            nonlocal end_ts
            while True:
                window = await queue.get()
                if window is None:
                    end_ts = time.monotonic()
                    break
                yield SpeechWindow(
                    data=convert_audio_format(
                        window.data, self.vad.audio_format, self.stt.audio_format
                    ),
                    time_ns=window.time_ns,
                    is_speech=window.is_speech,
                )

        seg_count = 0
        stt_stream = self.stt.stream(_window_iterator())
        async for segment in stt_stream:
            self._transcript.add_segment(segment)
            logger.info(
                "Transcription segment: %s (%.2fs-%.2fs)",
                segment.text,
                segment.start,
                segment.end,
            )
            self._notify("segment")
            seg_count += 1

        if seg_count > 0:
            if end_ts is not None:
                latency = time.monotonic() - end_ts
                log_level = logging.WARNING if latency > 0.5 else logging.INFO  # noqa: PLR2004
                logger.log(log_level, "STT utterance latency: %.3fs", latency)
            self._notify("utterance")
