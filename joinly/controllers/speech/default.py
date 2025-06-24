import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any, Self, cast

from semchunk.semchunk import chunkerify

from joinly.core import TTS, AudioWriter, SpeechController
from joinly.settings import get_settings
from joinly.types import (
    AudioFormat,
    SpeakerRole,
    SpeechInterruptedError,
    Transcript,
    TranscriptSegment,
)
from joinly.utils.audio import calculate_audio_duration, convert_audio_format
from joinly.utils.clock import Clock

logger = logging.getLogger(__name__)

_CHUNK_END = object()
_TEXT_END = object()


@dataclass
class SpeakJob:
    """A class to represent a job for speaking text."""

    text: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    exception: Exception | None = None


class DefaultSpeechController(SpeechController):
    """A class to manage the speech flow."""

    writer: AudioWriter
    tts: TTS
    no_speech_event: asyncio.Event

    def __init__(
        self,
        *,
        job_queue_size: int = 10,
        non_interruptable: float = 0.5,
    ) -> None:
        """Initialize the SpeechFlowController.

        Args:
            job_queue_size (int): The maximum size of the speech job queue
                (default is 10).
            non_interruptable (float): The duration in seconds from the start for
                which speech cannot be interrupted (default is 0.5).
        """
        self.job_queue_size = job_queue_size
        self.non_interruptable = non_interruptable
        self._job_queue: asyncio.Queue[SpeakJob] | None = None
        self._worker_task: asyncio.Task | None = None
        self._clock: Clock | None = None
        self._transcript: Transcript | None = None

    async def __aenter__(self) -> Self:
        """Enter the audio stream context."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the audio stream and clean up resources."""
        await self.stop()

    async def start(self, clock: Clock, transcript: Transcript) -> None:
        """Start the speech controller with the given writer and TTS.

        Args:
            clock (Clock): The clock to use for timing.
            transcript (Transcript): The transcript to be speech written to.
        """
        if self._job_queue is not None or self._worker_task is not None:
            msg = "Audio queue already started"
            raise RuntimeError(msg)

        self._job_queue = asyncio.Queue(maxsize=self.job_queue_size)
        self._clock = clock
        self._transcript = transcript
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """Stop the speech controller and clean up resources."""
        if self._worker_task is not None:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None

        if self._job_queue is not None:
            while not self._job_queue.empty():
                job = self._job_queue.get_nowait()
                logger.warning("Canceled speaking of: %s", job.text)
                job.done.set()
                self._job_queue.task_done()
            self._job_queue = None

        self._clock = None
        self._transcript = None

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
        if self._job_queue is None:
            msg = "Speech controller not active"
            raise RuntimeError(msg)

        logger.info("Enqueuing text: %s", text)

        job = SpeakJob(
            text=text, kwargs={"interrupt": interrupt, "interruptable": interruptable}
        )
        self._job_queue.put_nowait(job)

        await job.done.wait()
        if job.exception is not None:
            raise job.exception

    async def wait_until_no_speech(self) -> None:
        """Wait until all speech jobs in the queue are done."""
        if self._job_queue is None:
            msg = "Speech controller not active"
            raise RuntimeError(msg)
        await self._job_queue.join()

    async def _worker_loop(self) -> None:
        """Run the worker loop to process audio chunks."""
        if self._job_queue is None:
            msg = "Speech controller not active"
            raise RuntimeError(msg)

        while True:
            job = await self._job_queue.get()
            try:
                await self._speak_text(job.text, **job.kwargs)
            except Exception as e:  # noqa: BLE001
                job.exception = e
            finally:
                job.done.set()
                self._job_queue.task_done()

    async def _chunk_text(self, text: str) -> list[str]:
        """Chunk the text into smaller segments for processing.

        Args:
            text (str): The text to be chunked.

        Returns:
            list[str]: A list of text chunks.
        """
        chunker = chunkerify(
            lambda s: len(s.split()),
            chunk_size=max(15, min(50, int(0.2 * len(text.split())))),
        )
        chunks: list[str] = await asyncio.to_thread(chunker, text)  # type: ignore[operator]
        return chunks

    async def _speech_producer(
        self, chunks: list[str], queue: asyncio.Queue[object]
    ) -> None:
        """Produce speech segments and put them into the queue.

        Args:
            chunks (list[str]): The text to be spoken in chunks.
            queue (asyncio.Queue[object]): The queue to put the speech segments into.
        """
        for chunk in chunks:
            async for segment in self.tts.stream(chunk):
                await queue.put(segment)
            await queue.put(_CHUNK_END)
        await queue.put(_TEXT_END)

    async def _estimate_spoken_text(
        self, text: str, audio_byte_size: int, audio_format: AudioFormat
    ) -> str:
        """Estimate the spoken text based on the byte size and audio format.

        Args:
            text (str): The text to be spoken.
            audio_byte_size (int): The size of the audio in bytes.
            audio_format (AudioFormat): The audio format of the speech.

        Returns:
            str: The estimated spoken text.
        """
        wps = 1.8  # slow words per second to not over-estimate
        audio_duration = calculate_audio_duration(audio_byte_size, audio_format)
        word_num = int(audio_duration * wps)
        words = text.split(" ")
        return " ".join(words[: min(word_num, len(words))])

    async def _speak_text(  # noqa: C901, PLR0912, PLR0915
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
        if self._transcript is None or self._clock is None:
            msg = "Speech controller not active"
            raise RuntimeError(msg)

        chunks = await self._chunk_text(text)
        logger.info("Speaking text (chunks): %s", chunks)

        audio_queue: asyncio.Queue[object] = asyncio.Queue()
        chunk_idx: int = 0
        byte_size: int = 0
        chunk_byte_size: int = 0
        start: float | None = None

        producer = asyncio.create_task(self._speech_producer(chunks, audio_queue))
        buffer = bytearray()

        try:
            while True:
                try:
                    segment = audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    if byte_size > 0:
                        logger.warning(
                            'TTS is behind live speech on chunk %d: "%s"',
                            chunk_idx,
                            chunks[chunk_idx],
                        )
                    segment = await audio_queue.get()

                # await active speech to not interrupt it
                if not interrupt and chunk_idx == 0:
                    await self.no_speech_event.wait()

                if start is None:
                    start = self._clock.now_s

                # end of text chunk
                if segment is _CHUNK_END:
                    self._transcript.add_segment(
                        TranscriptSegment(
                            text=chunks[chunk_idx],
                            start=start,
                            end=self._clock.now_s,
                            speaker=get_settings().name,
                            role=SpeakerRole.assistant,
                        )
                    )
                    start = None
                    chunk_idx += 1
                    chunk_byte_size = 0
                    continue

                # end of text
                if segment is _TEXT_END:
                    if buffer:
                        await self.writer.write(bytes(buffer))
                        buffer.clear()
                    logger.info("Finished speaking text: %s", text)
                    break

                buffer.extend(
                    convert_audio_format(
                        cast("bytes", segment),
                        self.tts.audio_format,
                        self.writer.audio_format,
                    )
                )

                while len(buffer) >= self.writer.chunk_size:
                    # check for speech interruption
                    if (
                        interruptable
                        and not self.no_speech_event.is_set()
                        and calculate_audio_duration(
                            byte_size, self.writer.audio_format
                        )
                        > self.non_interruptable
                    ):
                        estimated_text = await self._estimate_spoken_text(
                            chunks[chunk_idx],
                            chunk_byte_size,
                            self.writer.audio_format,
                        )
                        self._transcript.add_segment(
                            TranscriptSegment(
                                text=estimated_text + "...",
                                start=start,
                                end=self._clock.now_s,
                                speaker=get_settings().name,
                                role=SpeakerRole.assistant,
                            )
                        )

                        spoken_text = " ".join([*chunks[:chunk_idx], estimated_text])
                        msg = (
                            f"Interrupted by detected speech. Spoken until now: "
                            f'"{spoken_text}"'
                        )
                        raise SpeechInterruptedError(msg)  # noqa: TRY301

                    await self.writer.write(bytes(buffer[: self.writer.chunk_size]))
                    byte_size += self.writer.chunk_size
                    chunk_byte_size += self.writer.chunk_size
                    del buffer[: self.writer.chunk_size]

        except SpeechInterruptedError as e:
            logger.info("%s", e)
            raise

        except Exception as e:
            msg = "Error while speaking text."
            logger.exception(msg)
            raise RuntimeError(msg) from e

        finally:
            producer.cancel()
