import abc
import logging
from collections.abc import AsyncIterator

from joinly.core import VAD
from joinly.types import AudioChunk, SpeechWindow
from joinly.utils.audio import calculate_audio_duration_ns

logger = logging.getLogger(__name__)


class BasePaddedVAD(VAD, abc.ABC):
    """A base vad implementation using fixed-size chunks."""

    @property
    @abc.abstractmethod
    def window_size_samples(self) -> int:
        """Expected window size in samples."""
        ...

    async def stream(
        self, chunks: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[SpeechWindow]:
        """Process the audio stream and yield speech segments.

        For non-speech segments, keeps one window in buffer to mark one previous
        window as well as speech.

        Args:
            chunks: An asynchronous iterator providing raw PCM audio data.

        Yields:
            SpeechWindow: A frame containing the audio segment, start time, and
                end time.
        """
        window_size: int = self.window_size_samples * self.audio_format.byte_depth
        chunk_ns: int = (
            self.window_size_samples * 1_000_000_000 // self.audio_format.sample_rate
        )
        time_ns: int = 0
        buffer = bytearray()
        pending: SpeechWindow | None = None

        async for chunk in chunks:
            buffer_ns = calculate_audio_duration_ns(len(buffer), self.audio_format)
            time_ns = chunk.time_ns - buffer_ns
            buffer.extend(chunk.data)

            while len(buffer) >= window_size:
                window_bytes = bytes(buffer[:window_size])
                is_speech = await self.is_speech(window_bytes)

                if not is_speech:
                    if pending:
                        yield pending
                    pending = SpeechWindow(
                        data=window_bytes,
                        time_ns=time_ns,
                        is_speech=False,
                        speaker=chunk.speaker,
                    )
                else:
                    if pending:
                        yield SpeechWindow(
                            data=pending.data,
                            time_ns=pending.time_ns,
                            is_speech=True,
                            speaker=pending.speaker,
                        )
                    pending = None

                    yield SpeechWindow(
                        data=window_bytes,
                        time_ns=time_ns,
                        is_speech=True,
                        speaker=chunk.speaker,
                    )

                del buffer[:window_size]
                time_ns += chunk_ns

        if pending:
            yield pending

    @abc.abstractmethod
    async def is_speech(self, window: bytes) -> bool:
        """Check if the given audio window contains speech.

        Args:
            window: A byte string representing the audio window.

        Returns:
            bool: True if the window contains speech, False otherwise.
        """
        ...
