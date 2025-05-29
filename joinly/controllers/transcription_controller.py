import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Self

from joinly.core import STT, VAD, AudioReader, TranscriptionController
from joinly.types import Transcript, VADWindow

logger = logging.getLogger(__name__)


class DefaultTranscriptionController(TranscriptionController):
    """A class to manage the transcription flow."""

    def __init__(  # noqa: PLR0913
        self,
        reader: AudioReader,
        vad: VAD,
        stt: STT,
        *,
        utterance_tail_seconds: float = 0.6,
        max_stt_tasks: int = 5,
        window_queue_size: int = 100,
    ) -> None:
        """Initialize the TranscriptionController.

        Args:
            reader (AudioReader): The audio reader to use for audio input.
            vad (VAD): The voice activity detection service to use.
            stt (STT): The speech-to-text service to use for transcription.
            utterance_tail_seconds (float): The duration in seconds to wait after the
                last detected speech before considering the utterance complete
                (default is 0.6).
            max_stt_tasks (int): The maximum number of concurrent STT tasks
                (default is 5).
            window_queue_size (int): The maximum size of the window queue
                (default is 100).
        """
        self._reader = reader
        self._vad = vad
        self._stt = stt
        self.utterance_tail_seconds = utterance_tail_seconds
        self.max_stt_tasks = max_stt_tasks
        self.window_queue_size = window_queue_size
        self._transcript = Transcript()
        self._vad_task: asyncio.Task | None = None
        self._stt_task: asyncio.Task | None = None
        self._window_queue: asyncio.Queue[VADWindow | None] | None = None
        self._stt_tasks: set[asyncio.Task] = set()
        self._no_speech_event = asyncio.Event()
        self._listeners: set[Callable[[str], Coroutine[None, None, None]]] = set()

    @property
    def transcript(self) -> Transcript:
        """Get the current transcript."""
        return self._transcript

    @property
    def no_speech_event(self) -> asyncio.Event:
        """Get the event that is set when no speech is detected."""
        return self._no_speech_event

    async def __aenter__(self) -> Self:
        """Set up the transcription controller."""
        if self._vad_task is not None or self._stt_task is not None:
            msg = "Transcription controller already started"
            raise RuntimeError(msg)

        self._no_speech_event.clear()
        self._vad_task = asyncio.create_task(self._vad_worker())

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up the transcription controller."""
        if self._vad_task is not None:
            self._vad_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._vad_task
            self._vad_task = None

        if self._stt_task is not None:
            self._stt_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stt_task
            self._stt_task = None

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
        last_speech: float = float("inf")
        dropped_frames: int = 0

        vad_stream = self._vad.stream(self._reader)
        async for frame in vad_stream:
            if frame.is_speech:
                last_speech = frame.start

            if frame.is_speech and self._window_queue is None:
                # utterance start
                logger.info("Utterance start: %.2fs", frame.start)
                self._no_speech_event.clear()
                if len(self._stt_tasks) >= self.max_stt_tasks:
                    logger.warning(
                        "Maximum number of STT tasks reached (%d), dropping frame",
                        self.max_stt_tasks,
                    )
                    continue

                self._window_queue = asyncio.Queue[VADWindow | None](
                    maxsize=self.window_queue_size
                )
                task = asyncio.create_task(self._stt_utterance(self._window_queue))
                task.add_done_callback(lambda t: self._stt_tasks.discard(t))
                self._stt_tasks.add(task)

            if (
                not frame.is_speech
                and frame.start - last_speech >= self.utterance_tail_seconds
            ):
                # utterance end
                logger.info("Utterance end: %.2fs", frame.start)
                self._no_speech_event.set()
                last_speech = float("inf")
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
                    self._window_queue.put_nowait(frame)
                except asyncio.QueueFull:
                    dropped_frames += 1
                    if dropped_frames == 1:
                        logger.info("Frame queue is full, dropping frames")
                else:
                    if dropped_frames > 0:
                        logger.warning(
                            "Dropped %d frames due to full queue", dropped_frames
                        )
                    dropped_frames = 0

    async def _stt_utterance(self, queue: asyncio.Queue[VADWindow | None]) -> None:
        """Process speech frames for transcription."""
        end_ts: float | None = None

        async def _frame_iterator() -> AsyncIterator[VADWindow]:
            """Yield frames from the frame queue."""
            nonlocal end_ts
            while True:
                frame = await queue.get()
                if frame is None:
                    end_ts = time.monotonic()
                    break
                yield frame

        seg_count = 0
        stt_stream = self._stt.stream(_frame_iterator())
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
                logger.info("Utterance latency: %.3fs", time.monotonic() - end_ts)
            self._notify("utterance")
