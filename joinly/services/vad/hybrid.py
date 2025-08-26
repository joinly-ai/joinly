import logging
from contextlib import AsyncExitStack
from typing import Self

from joinly.services.vad.base import BasePaddedVAD
from joinly.services.vad.silero import SileroVAD
from joinly.services.vad.webrtc import WebrtcVAD
from joinly.types import AudioFormat
from joinly.utils.audio import convert_audio_format

logger = logging.getLogger(__name__)


class HybridVAD(BasePaddedVAD):
    """Hybrid VAD combining Silero and Webrtc VADs.

    Mainly utilizes Webrtc for higher computational efficiency. Confirms
    first speech detections using Silero to avoid false detections.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        webrtc_aggressiveness: int = 3,
        silero_speech_threshold: float = 0.75,
    ) -> None:
        """Hybrid VAD initialization.

        Args:
            sample_rate (int, optional): The sample rate of the audio. Defaults
                to 16000.
            webrtc_aggressiveness (int, optional): The aggressiveness level for
                Webrtc VAD. Defaults to 3.
            silero_speech_threshold (float, optional): The speech threshold for
                Silero VAD. Defaults to 0.75.
        """
        self._webrtc = WebrtcVAD(
            sample_rate=sample_rate,
            window_duration=30,
            aggressiveness=webrtc_aggressiveness,
        )
        self._silero = SileroVAD(
            sample_rate=sample_rate,
            speech_threshold=silero_speech_threshold,
            use_state=True,
        )
        self.audio_format = AudioFormat(
            sample_rate=sample_rate, byte_depth=self._webrtc.audio_format.byte_depth
        )
        self._last_is_speech: bool = False
        self._last_used_silero: bool = False
        self._padding = (
            b"\x00"
            * self._webrtc.audio_format.byte_depth
            * (self._silero.window_size_samples - self._webrtc.window_size_samples)
        )
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> Self:
        """Initialize the hybrid VAD."""
        self._last_is_speech = False
        self._last_used_silero = False
        await self._stack.enter_async_context(self._webrtc)
        await self._stack.enter_async_context(self._silero)
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
            is_speech = await self._silero_is_speech(window)
        else:
            self._last_used_silero = False

        self._last_is_speech = is_speech
        return is_speech

    async def _silero_is_speech(self, window: bytes) -> bool:
        """Check if the audio window contains speech using Silero VAD."""
        if not self._last_used_silero:
            self._silero.reset_state()
        self._last_used_silero = True
        return await self._silero.is_speech(
            convert_audio_format(
                self._padding + window,
                self._webrtc.audio_format,
                self._silero.audio_format,
            )
        )
