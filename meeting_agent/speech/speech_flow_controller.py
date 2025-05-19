import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Self

from meeting_agent.devices.virtual_microphone import VirtualMicrophone
from meeting_agent.speech.tts_service import TTSService

logger = logging.getLogger(__name__)


@dataclass
class SpeakJob:
    """A class to represent a job for speaking text."""

    text: str
    done: asyncio.Event
    interrupt: bool


class SpeechFlowController:
    """A class to manage the speech flow."""

    def __init__(
        self,
        mic: VirtualMicrophone,
        tts: TTSService,
        no_speech_event: asyncio.Event,
        *,
        queue_size: int = 10,
    ) -> None:
        """Initialize the SpeechFlowController.

        Args:
            mic (VirtualMicrophone): The virtual microphone to use for audio input.
            tts (TTSService): The text-to-speech service to use for audio output.
            no_speech_event (asyncio.Event): An event to signal when no speech is
                detected.
            queue_size (int): The maximum size of the speech queue (default is 10).
        """
        self._mic = mic
        self._tts = tts
        self._no_speech_event = no_speech_event
        self.queue_size = queue_size
        self._chunk_size = mic.chunk_size
        self._queue: asyncio.Queue[SpeakJob] | None = None
        self._worker_task: asyncio.Task | None = None

    async def __aenter__(self) -> Self:
        """Set up the audio stream and queue."""
        if self._queue is not None or self._worker_task is not None:
            msg = "Audio queue already started"
            raise RuntimeError(msg)

        self._queue = asyncio.Queue(maxsize=self.queue_size)
        self._worker_task = asyncio.create_task(self._worker_loop())

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the audio stream and clean up resources."""
        if self._worker_task is not None:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None

        if self._queue is not None:
            while not self._queue.empty():
                job = self._queue.get_nowait()
                logger.warning("Canceled speaking of: %s", job.text)
                job.done.set()
                self._queue.task_done()
            self._queue = None

    async def speak_text(
        self, text: str, *, wait: bool = True, interrupt: bool = False
    ) -> None:
        """Speak the given text using the virtual microphone.

        Args:
            text (str): The text to be spoken.
            wait (bool): Whether to wait for the speech to finish.
            interrupt (bool): Whether to interrupt and ignore detected speech.

        Raises:
            QueueFull: If the queue is full.
        """
        if self._queue is None:
            msg = "Audio queue not initialized"
            raise RuntimeError(msg)

        logger.info("Enqueuing text: %s", text)

        done_event = asyncio.Event()
        self._queue.put_nowait(
            SpeakJob(text=text, done=done_event, interrupt=interrupt)
        )

        if wait:
            await done_event.wait()

    async def _worker_loop(self) -> None:
        """Run the worker loop to process audio chunks."""
        if self._queue is None:
            msg = "Audio queue not initialized"
            raise RuntimeError(msg)

        while True:
            job = await self._queue.get()
            try:
                await self._speak_text(job.text, interrupt=job.interrupt)
                job.done.set()
            finally:
                self._queue.task_done()

    async def _speak_text(self, text: str, *, interrupt: bool) -> None:
        """Speak the given text using the virtual microphone.

        Args:
            text (str): The text to be spoken.
            interrupt (bool): Whether to interrupt and ignore detected speech.
        """
        logger.info("Speaking text: %s", text)

        tts_generator = self._tts.tts(text)

        async def _next_chunk() -> bytes:
            return await tts_generator.__anext__()

        next_chunk = asyncio.create_task(_next_chunk())
        chunk_num: int = 0

        try:
            while True:
                try:
                    if chunk_num > 0 and not next_chunk.done():
                        logger.warning(
                            "TTS is behind live speech on chunk %d", chunk_num
                        )

                    chunk = await next_chunk
                except StopAsyncIteration:
                    break

                next_chunk = asyncio.create_task(_next_chunk())

                for i in range(0, len(chunk), self._chunk_size):
                    if not interrupt:
                        await self._no_speech_event.wait()
                    await self._mic.write(chunk[i : i + self._chunk_size])

                chunk_num += 1
        finally:
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                next_chunk.cancel()
