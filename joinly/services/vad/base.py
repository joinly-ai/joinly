import abc
import logging
from collections.abc import AsyncIterator

from joinly.core import VAD
from joinly.types import SpeechWindow
from joinly.utils.logging import LOGGING_TRACE

logger = logging.getLogger(__name__)


class BasePaddedVAD(VAD, abc.ABC):
    """A base vad implementation using fixed-size chunks."""

    @property
    @abc.abstractmethod
    def window_size_samples(self) -> int:
        """Expected window size in samples."""
        ...

    async def stream(self, data: AsyncIterator[bytes]) -> AsyncIterator[SpeechWindow]:
        """Process the audio stream and yield speech segments.

        For non-speech segments, keeps one window in buffer to mark one previous
        window as well as speech.

        Args:
            data: An asynchronous iterator providing raw PCM audio data.

        Yields:
            SpeechWindow: A frame containing the audio segment, start time, and
                end time.
        """
        idx: int = 0
        window_size: int = self.window_size_samples * self.audio_format.byte_depth
        chunk_dur: float = self.window_size_samples / self.audio_format.sample_rate
        buffer = bytearray()
        pending: bytes = b""
        last_is_speech: bool = False

        async for chunk in data:
            buffer.extend(chunk)

            while len(buffer) >= window_size:
                window_bytes = bytes(buffer[:window_size])
                is_speech = await self.is_speech(window_bytes)

                logger.log(
                    LOGGING_TRACE,
                    "Processing window %d of size %d: is_speech=%s",
                    idx,
                    len(window_bytes),
                    is_speech,
                )

                if not is_speech:
                    if pending:
                        yield SpeechWindow(
                            data=pending,
                            start=(idx - 1) * chunk_dur,
                            is_speech=last_is_speech,
                        )
                    pending = window_bytes
                else:
                    if pending:
                        yield SpeechWindow(
                            data=pending,
                            start=(idx - 1) * chunk_dur,
                            is_speech=True,
                        )
                    pending = b""

                    yield SpeechWindow(
                        data=window_bytes,
                        start=idx * chunk_dur,
                        is_speech=True,
                    )

                del buffer[:window_size]
                idx += 1
                last_is_speech = is_speech

        if pending:
            yield SpeechWindow(
                data=pending,
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
