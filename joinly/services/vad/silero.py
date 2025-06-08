import asyncio
import logging
from typing import Self

from silero_vad_lite import SileroVAD as SileroVADModel

from joinly.services.vad.base import BasePaddedVAD
from joinly.types import AudioFormat

logger = logging.getLogger(__name__)


class SileroVAD(BasePaddedVAD):
    """Voice activity detection using Silero."""

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        speech_threshold: float = 0.5,
    ) -> None:
        """Initialize the VADService.

        Args:
            sample_rate: The sample rate of the audio data (default is 16000).
            speech_threshold: The threshold for speech detection (default is 0.5).
        """
        if sample_rate not in (8000, 16000):
            msg = (
                f"Unsupported sample rate {sample_rate}. "
                "Supported sample rates are 8000 and 16000."
            )
            raise ValueError(msg)

        self._sample_rate = sample_rate
        self._speech_threshold = speech_threshold
        self._model: SileroVADModel | None = None
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=4)

    async def __aenter__(self) -> Self:
        """Initialize the VAD model and prepare for processing."""
        logger.info("Loading VAD model")
        self._model = await asyncio.to_thread(
            SileroVADModel,
            self._sample_rate,
        )
        logger.info("Loaded VAD model")

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources."""
        if self._model is not None:
            del self._model
            self._model = None

    @property
    def window_size_samples(self) -> int:
        """Expected window size in samples."""
        if self._model is None:
            msg = "VAD model is not initialized"
            raise RuntimeError(msg)
        return self._model.window_size_samples

    async def is_speech(self, window: bytes) -> bool:
        """Check if the given audio window contains speech.

        Args:
            window: The audio window to check.

        Returns:
            bool: True if the window contains speech, False otherwise.
        """
        if self._model is None:
            msg = "VAD model is not initialized"
            raise RuntimeError(msg)

        speech_prob = self._model.process(window)

        return speech_prob > self._speech_threshold
