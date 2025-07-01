import asyncio
import logging
from typing import Self, cast

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


class DefaultSpeechController(SpeechController):
    """A class to manage the speech flow."""

    writer: AudioWriter
    tts: TTS
    no_speech_event: asyncio.Event

    def __init__(
        self,
        *,
        prefetch_chunks: int = 3,
    ) -> None:
        """Initialize the SpeechFlowController.

        Args:
            prefetch_chunks (int): The number of chunks to prefetch for speech
                synthesis (default is 3).
        """
        self.prefetch_chunks = prefetch_chunks
        self._clock: Clock | None = None
        self._transcript: Transcript | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        """Enter the audio stream context."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the audio stream and clean up resources."""
        await self.stop()

    async def start(self, clock: Clock, transcript: Transcript) -> None:
        """Start the speech controller.

        Args:
            clock (Clock): The clock to use for timing.
            transcript (Transcript): The transcript to be speech written to.
        """
        if self._clock is not None or self._transcript is not None:
            msg = "Speech controller already active"
            raise RuntimeError(msg)

        self._clock = clock
        self._transcript = transcript

    async def stop(self) -> None:
        """Stop the speech controller."""
        self._clock = None
        self._transcript = None

    async def speak_text(self, text: str) -> None:
        """Speak the given text using the virtual microphone.

        Args:
            text (str): The text to be spoken.
        """
        try:
            async with self._lock, asyncio.TaskGroup() as tg:
                chunks: list[str] = await self._chunk_text(text)
                audio_queue: asyncio.Queue[bytes | object] = asyncio.Queue()
                prefetch_sem = asyncio.Semaphore(self.prefetch_chunks)
                tg.create_task(
                    self._speech_producer(
                        chunks,
                        audio_queue,
                        prefetch_sem,
                    )
                )
                tg.create_task(
                    self._speech_consumer(
                        chunks,
                        audio_queue,
                        prefetch_sem,
                    )
                )
        except* SpeechInterruptedError as eg:
            raise eg.exceptions[0] from None
        except* Exception as eg:
            msg = "Error while speaking text"
            logger.exception(msg)
            raise RuntimeError(msg) from eg

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
        self,
        chunks: list[str],
        audio_queue: asyncio.Queue[bytes | object],
        prefetch_sem: asyncio.Semaphore,
    ) -> None:
        """Produce speech segments and put them into the queue.

        Args:
            chunks (list[str]): The text to be spoken in chunks.
            audio_queue (asyncio.Queue[bytes | object]): The queue to put the speech
                segments into.
            prefetch_sem (asyncio.Semaphore): Semaphore to limit the number of
                prefetched chunks.
        """
        for chunk in chunks:
            await prefetch_sem.acquire()
            async for segment in self.tts.stream(chunk):
                await audio_queue.put(segment)
            await audio_queue.put(_CHUNK_END)
        await audio_queue.put(_TEXT_END)

    async def _speech_consumer(
        self,
        chunks: list[str],
        audio_queue: asyncio.Queue[bytes | object],
        prefetch_sem: asyncio.Semaphore,
    ) -> None:
        """Speak the given audio using the virtual microphone.

        Args:
            chunks (list[str]): The text to be spoken in chunks.
            audio_queue (asyncio.Queue[bytes | object]): The queue to get the audio
                segments from.
            prefetch_sem (asyncio.Semaphore): Semaphore to limit the number of
                prefetched chunks.

        Raises:
            SpeechInterruptedError: If the speech was interrupted.
        """
        if self._transcript is None or self._clock is None:
            msg = "Speech controller not active"
            raise RuntimeError(msg)

        chunk_idx: int = 0
        byte_size: int = 0
        start = self._clock.now_s
        buffer = bytearray()

        while True:
            segment = await audio_queue.get()

            if segment is _TEXT_END:
                break

            if segment is _CHUNK_END:
                if buffer:
                    await self.writer.write(bytes(buffer))
                    buffer.clear()
                self._transcript.add_segment(
                    TranscriptSegment(
                        text=chunks[chunk_idx],
                        start=start,
                        end=self._clock.now_s,
                        speaker=get_settings().name,
                        role=SpeakerRole.assistant,
                    )
                )
                prefetch_sem.release()
                logger.info(
                    'Spoken (%d/%d): "%s"',
                    chunk_idx + 1,
                    len(chunks),
                    chunks[chunk_idx],
                )
                chunk_idx += 1
                byte_size = 0
                continue

            buffer.extend(
                convert_audio_format(
                    cast("bytes", segment),
                    self.tts.audio_format,
                    self.writer.audio_format,
                )
            )

            while len(buffer) >= self.writer.chunk_size:
                # check for speech interruption
                if not self.no_speech_event.is_set():
                    estimated_text = (
                        await self._estimate_spoken_text(
                            chunks[chunk_idx], byte_size, self.writer.audio_format
                        )
                        + "..."
                    )
                    self._transcript.add_segment(
                        TranscriptSegment(
                            text=estimated_text,
                            start=start if byte_size > 0 else self._clock.now_s,
                            end=self._clock.now_s,
                            speaker=get_settings().name,
                            role=SpeakerRole.assistant,
                        )
                    )
                    logger.info(
                        'Spoken (%d/%d): "%s" (interrupted)',
                        chunk_idx + 1,
                        len(chunks),
                        estimated_text,
                    )
                    spoken_text = " ".join([*chunks[:chunk_idx], estimated_text])
                    raise SpeechInterruptedError(spoken_text=spoken_text)

                await self.writer.write(bytes(buffer[: self.writer.chunk_size]))
                if byte_size == 0:
                    start = self._clock.now_s
                byte_size += self.writer.chunk_size
                del buffer[: self.writer.chunk_size]

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
        wps = 2.0  # rough words per second
        audio_duration = calculate_audio_duration(audio_byte_size, audio_format)
        word_num = int(audio_duration * wps)
        words = text.split(" ")
        return " ".join(words[: min(word_num, len(words))])
