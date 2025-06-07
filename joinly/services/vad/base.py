import abc
import logging
from collections.abc import AsyncIterator

from joinly.core import VAD, AudioReader
from joinly.utils.audio import convert_byte_depth
from joinly.utils.logging import LOGGING_TRACE

logger = logging.getLogger(__name__)


class BasePaddedVAD(VAD, abc.ABC):
    """A base vad implementation using fixed-size chunks ."""

    @property
    @abc.abstractmethod
    def sample_rate(self) -> int:
        """Expected sample rate of the audio data."""
        ...

    @property
    @abc.abstractmethod
    def byte_depth(self) -> int:
        """Expected byte depth of the audio data (e.g., 2 for 16-bit PCM)."""
        ...

    @property
    @abc.abstractmethod
    def window_size_samples(self) -> int:
        """Expected window size in samples."""
        ...

    async def stream(self, reader: AudioReader) -> AsyncIterator[VADWindow]:
        """Process the audio stream and yield speech segments.

        For non-speech segments, keeps one window in buffer to mark one previous
        window as well as speech.

        Args:
            reader: An AudioReader providing audio data.

        Yields:
            VADFrame: A frame containing the audio segment, start time, and end time.
        """
        if reader.sample_rate != self.sample_rate:
            msg = f"Expected sample rate {self.sample_rate}, got {reader.sample_rate}"
            raise ValueError(msg)

        idx: int = 0
        window_size: int = self.window_size_samples * reader.byte_depth
        chunk_dur: float = self.window_size_samples / reader.sample_rate
        buffer = bytearray()
        pending: bytes = b""
        last_is_speech: bool = False

        while True:
            chunk = await reader.read()
            if not chunk:
                break
            buffer.extend(chunk)

            while len(buffer) >= window_size:
                window_bytes = bytes(buffer[:window_size])

                is_speech = await self.is_speech(
                    convert_byte_depth(
                        window_bytes, reader.byte_depth, self.byte_depth
                    )
                )

                logger.log(
                    LOGGING_TRACE,
                    "Processing window %d of size %d: is_speech=%s",
                    idx,
                    len(window_bytes),
                    is_speech,
                )

                if not is_speech:
                    if pending:
                        yield VADWindow(
                            pcm=pending,
                            start=(idx - 1) * chunk_dur,
                            is_speech=last_is_speech,
                        )
                    pending = window_bytes
                else:
                    if pending:
                        yield VADWindow(
                            pcm=pending,
                            start=(idx - 1) * chunk_dur,
                            is_speech=True,
                        )
                    pending = b""

                    yield VADWindow(
                        pcm=window_bytes,
                        start=idx * chunk_dur,
                        is_speech=True,
                    )

                del buffer[:window_size]
                idx += 1
                last_is_speech = is_speech

        if pending:
            yield VADWindow(
                pcm=pending,
                start=(idx - 1) * chunk_dur,
                is_speech=last_is_speech,
            )

    @abc.abstractmethod
    async def is_speech(self, window: bytes) -> bool:
        """Check if the given audio window contains speech.

        Args:
            window: A byte string representing the audio window.

        Returns:
            bool: True if the window contains speech, False otherwise.
        """
        ...
