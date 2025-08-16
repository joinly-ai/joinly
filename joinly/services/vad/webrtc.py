import logging
from typing import Self

import webrtcvad

from joinly.services.vad.base import BasePaddedVAD
from joinly.types import AudioFormat

logger = logging.getLogger(__name__)


class WebrtcVAD(BasePaddedVAD):
    """Voice activity detection using webrtcvad."""

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        window_duration: int = 30,
        aggressiveness: int = 3,
    ) -> None:
        """Initialize webrtc VAD.

        Args:
            sample_rate: The sample rate of the audio data (default is 16000).
            window_duration: The duration of each window in ms (default is 30).
                This determines the size of the audio chunks processed by VAD.
            aggressiveness: The aggressiveness level for VAD (0-3, default is 3).
        """
        if sample_rate not in (8000, 16000, 32000, 48000):
            msg = (
                f"Unsupported sample rate {sample_rate}. "
                "Supported sample rates are 8000, 16000, 32000, and 48000."
            )
            raise ValueError(msg)
        if window_duration not in (10, 20, 30):
            msg = (
                f"Unsupported window duration {window_duration}. "
                "Supported window durations are 10, 20, and 30 milliseconds."
            )
            raise ValueError(msg)

        self._sample_rate = sample_rate
        self._window_duration = window_duration
        self._aggressiveness = aggressiveness
        self._window_size_samples = int(
            self._sample_rate * self._window_duration / 1000
        )
        self._vad: webrtcvad.Vad | None = None
        self.audio_format = AudioFormat(sample_rate=self._sample_rate, byte_depth=2)

    async def __aenter__(self) -> Self:
        """Initialize webrtc VAD."""
        self._vad = webrtcvad.Vad(self._aggressiveness)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources."""
        if self._vad is not None:
            del self._vad
            self._vad = None

    @property
    def window_size_samples(self) -> int:
        """Expected window size in samples."""
        return self._window_size_samples

    async def is_speech(self, window: bytes) -> bool:
        """Check if the given audio window contains speech.

        Args:
            window: The audio window to check.

        Returns:
            bool: True if the window contains speech, False otherwise.
        """
        if self._vad is None:
            msg = "VAD is not initialized"
            raise RuntimeError(msg)

        return self._vad.is_speech(window, self._sample_rate, self._window_size_samples)
