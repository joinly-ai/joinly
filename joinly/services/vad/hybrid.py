from contextlib import AsyncExitStack
from typing import Self

from joinly.services.vad.base import BasePaddedVAD
from joinly.services.vad.silero import SileroVAD
from joinly.services.vad.webrtc import WebrtcVAD
from joinly.types import AudioFormat
from joinly.utils.audio import convert_audio_format


class HybridVAD(BasePaddedVAD):
    """Hybrid VAD combining Silero and Webrtc VADs.

    Mainly utilizing Webrtc for higher computational efficiency. Confirms
    first speech detections using Silero to avoid false detections.
    """

    def __init__(self, *, sample_rate: int = 16000) -> None:
        """Hybrid VAD initialization.

        Args:
            sample_rate (int, optional): The sample rate of the audio. Defaults
                to 16000.
        """
        self._silero = SileroVAD(sample_rate=sample_rate)
        self._webrtc = WebrtcVAD(
            sample_rate=sample_rate, window_duration=30, aggressiveness=3
        )
        self.audio_format = AudioFormat(
            sample_rate=sample_rate, byte_depth=self._webrtc.audio_format.byte_depth
        )
        self._last_is_speech: bool = False
        self._padding = (
            b"\x00"
            * self._webrtc.audio_format.byte_depth
            * (self._silero.window_size_samples - self._webrtc.window_size_samples)
        )
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> Self:
        """Initialize the hybrid VAD."""
        self._last_is_speech = False
        await self._stack.enter_async_context(self._silero)
        await self._stack.enter_async_context(self._webrtc)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources."""
        await self._stack.aclose()

    @property
    def window_size_samples(self) -> int:
        """Expected window size in samples."""
        return self._webrtc.window_size_samples

    async def is_speech(self, window: bytes) -> bool:
        """Check if the audio window contains speech.

        Mainly uses webrtc for computational efficiency. To avoid false speech
        detections, silero is used as well for a detected speech by webrtc after a
        no speech segment.

        Args:
            window (bytes): The audio window to check.

        Returns:
            bool: True if the window contains speech, False otherwise.
        """
        is_speech = await self._webrtc.is_speech(window)
        if is_speech and not self._last_is_speech:
            is_speech = await self._silero.is_speech(
                convert_audio_format(
                    window + self._padding,
                    self._webrtc.audio_format,
                    self._silero.audio_format,
                )
            )
        self._last_is_speech = is_speech
        return is_speech
