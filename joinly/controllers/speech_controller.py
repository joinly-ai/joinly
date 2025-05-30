import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any, Self

from joinly.core import TTS, AudioWriter, SpeechController
from joinly.types import SpeechSegment

logger = logging.getLogger(__name__)


@dataclass
class SpeakJob:
    """A class to represent a job for speaking text."""

    text: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    exception: Exception | None = None


class DefaultSpeechController(SpeechController):
    """A class to manage the speech flow."""

    def __init__(
        self,
        writer: AudioWriter,
        tts: TTS,
        no_speech_event: asyncio.Event,
        *,
        queue_size: int = 10,
        non_interruptable: float = 0.5,
    ) -> None:
        """Initialize the SpeechFlowController.

        Args:
            writer (AudioWriter): The audio writer to use for audio output.
            tts (TTS): The text-to-speech service to use for audio output.
            no_speech_event (asyncio.Event): An event to signal when no speech is
                detected.
            queue_size (int): The maximum size of the speech queue (default is 10).
            non_interruptable (float): The duration in seconds from the start for
                which speech cannot be interrupted (default is 0.5).
        """
        self._writer = writer
        self._tts = tts
        self._no_speech_event = no_speech_event
        self.queue_size = queue_size
        self.non_interruptable = non_interruptable
        self._chunk_size = writer.chunk_size
        self._chunk_dur = writer.chunk_size / (writer.sample_rate * writer.byte_depth)
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
        self,
        text: str,
        *,
        interrupt: bool = False,
        interruptable: bool = True,
    ) -> None:
        """Speak the given text using the virtual microphone.

        Args:
            text (str): The text to be spoken.
            interrupt (bool): Whether to interrupt detected speech. Else wait for
                the speech to finish.
            interruptable (bool): Whether this speech can be interrupted by detected
                speech.

        Raises:
            QueueFull: If the queue is full.
        """
        if self._queue is None:
            msg = "Audio queue not initialized"
            raise RuntimeError(msg)

        logger.info("Enqueuing text: %s", text)

        job = SpeakJob(
            text=text, kwargs={"interrupt": interrupt, "interruptable": interruptable}
        )
        self._queue.put_nowait(job)

        await job.done.wait()
        if job.exception is not None:
            raise job.exception

    async def wait_until_no_speech(self) -> None:
        """Wait until all speech jobs in the queue are done."""
        if self._queue is None:
            msg = "Audio queue not initialized"
            raise RuntimeError(msg)
        await self._queue.join()

    async def _worker_loop(self) -> None:
        """Run the worker loop to process audio chunks."""
        if self._queue is None:
            msg = "Audio queue not initialized"
            raise RuntimeError(msg)

        while True:
            job = await self._queue.get()
            try:
                await self._speak_text(job.text, **job.kwargs)
            except Exception as e:  # noqa: BLE001
                job.exception = e
            finally:
                job.done.set()
                self._queue.task_done()

    async def _speak_text(  # noqa: C901
        self, text: str, *, interrupt: bool, interruptable: bool
    ) -> None:
        """Speak the given text using the virtual microphone.

        Args:
            text (str): The text to be spoken.
            interrupt (bool): Whether to interrupt and ignore detected speech.
            interruptable (bool): Whether this speech can be interrupted.

        Raises:
            RuntimeError: If the speech was interrupted.
        """
        logger.info("Speaking text: %s", text)

        tts_stream = self._tts.stream(text)

        async def _next_segment() -> SpeechSegment:
            return await tts_stream.__anext__()

        next_segment = asyncio.create_task(_next_segment())
        chunk_num: int = 0
        spoken_text: list[str] = []
        interrupted: bool = False

        try:
            while True:
                try:
                    if chunk_num > 0 and not next_segment.done():
                        logger.warning(
                            "TTS is behind live speech on chunk %d. "
                            'Spoken text until now: "%s"',
                            chunk_num,
                            " ".join(spoken_text),
                        )

                    segment = await next_segment
                except StopAsyncIteration:
                    break

                next_segment = asyncio.create_task(_next_segment())

                if not interrupt and chunk_num == 0:
                    await self._no_speech_event.wait()

                for i in range(0, len(segment.pcm), self._chunk_size):
                    if (
                        interruptable
                        and chunk_num * self._chunk_dur >= self.non_interruptable
                        and not self._no_speech_event.is_set()
                    ):
                        # estimate spoken text until interruption
                        chunk_words = segment.text.split(" ")
                        spoken_chunk_text = chunk_words[
                            : int(i / len(segment.pcm) * len(chunk_words))
                        ]
                        spoken_text.extend(spoken_chunk_text)
                        interrupted = True
                        break

                    await self._writer.write(segment.pcm[i : i + self._chunk_size])
                    chunk_num += 1

                if interrupted:
                    break
                spoken_text.append(segment.text)

        except Exception as e:
            msg = (
                f"Error while speaking text. "
                f'Spoken text until now: "{" ".join(spoken_text)}"'
            )
            logger.exception(msg)
            raise RuntimeError(msg) from e

        finally:
            next_segment.cancel()

        if interrupted:
            msg = (
                f"Interrupted by detected speech. "
                f'Spoken text until now: "{" ".join(spoken_text)}"'
            )
            logger.warning(msg)
            raise RuntimeError(msg)
