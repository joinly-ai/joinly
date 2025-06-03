import abc
import logging
from collections.abc import AsyncIterator

import numpy as np

from joinly.core import VAD, AudioReader
from joinly.types import VADWindow
from joinly.utils import LOGGING_TRACE

logger = logging.getLogger(__name__)

BYTE_DEPTH_16 = 2
BYTE_DEPTH_32 = 4


def _convert_byte_depth(data: bytes, source_depth: int, target_depth: int) -> bytes:
    """Convert the byte depth of the audio data.

    Args:
        data: A byte string representing the audio data.
        source_depth: The byte depth of the source audio data.
        target_depth: The desired byte depth for the output audio data.

    Returns:
        bytes: The audio data converted to the target byte depth.

    Raises:
        ValueError: If the source and target byte depths are incompatible.
    """
    if source_depth == target_depth:
        return data

    if source_depth == BYTE_DEPTH_32 and target_depth == BYTE_DEPTH_16:
        floats = np.frombuffer(data, dtype=np.float32)
        ints = np.clip(floats * 32767.0, -32768, 32767).astype(np.int16)
        return ints.tobytes()

    if source_depth == BYTE_DEPTH_16 and target_depth == BYTE_DEPTH_32:
        ints = np.frombuffer(data, dtype=np.int16)
        floats = ints.astype(np.float32) / 32767.0
        return floats.tobytes()

    msg = (
        f"Incompatible byte depths: source={source_depth}, target={target_depth}. "
        "Only conversion between 16-bit and 32-bit PCM is supported."
    )
    raise ValueError(msg)


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
                    _convert_byte_depth(
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
