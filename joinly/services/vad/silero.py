import asyncio
import logging
import os
import pathlib
from typing import Self

import numpy as np
import onnxruntime as ort

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
        use_state: bool = True,
    ) -> None:
        """Initialize the VADService.

        Args:
            sample_rate: The sample rate of the audio data (default is 16000).
            speech_threshold: The threshold for speech detection (default is 0.5).
            use_state: Whether to use stateful VAD (default is True).
        """
        if sample_rate not in (8000, 16000):
            msg = (
                f"Unsupported sample rate {sample_rate}. "
                "Supported sample rates are 8000 and 16000."
            )
            raise ValueError(msg)

        self._sample_rate = sample_rate
        self._speech_threshold = speech_threshold
        self._use_state = use_state
        self._session: ort.InferenceSession | None = None
        self._state: np.ndarray | None = None
        self._sr_tensor = np.array([self._sample_rate], dtype=np.int64)
        self._window_size_samples: int = 512 if sample_rate == 16000 else 256  # noqa: PLR2004
        self.audio_format = AudioFormat(sample_rate=sample_rate, byte_depth=4)

    async def __aenter__(self) -> Self:
        """Initialize the VAD model and prepare for processing."""
        cache_dir = (
            pathlib.Path(os.getenv("XDG_CACHE_HOME", "~/.cache")).expanduser()
            / "silero"
        )
        if not cache_dir.exists():
            msg = (
                f"Silero VAD cache directory {cache_dir} does not exist. "
                "Make sure to download the model first "
                "(uv run scripts/download_assets.py)."
            )
            raise RuntimeError(msg)

        logger.info("Loading ONNX Silero VAD model")
        options = ort.SessionOptions()
        self._session = ort.InferenceSession(
            str(cache_dir / "silero_vad.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        logger.debug("Loaded VAD model")

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Clean up resources."""
        if self._session is not None:
            del self._session
            self._session = None

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
        if self._session is None or self._state is None:
            msg = "VAD model is not initialized"
            raise RuntimeError(msg)

        input_data = np.frombuffer(window, dtype=np.float32)
        if input_data.shape[0] != self.window_size_samples:
            msg = (
                "Window size does not match expected size, expected "
                f"{self.window_size_samples} samples, got {input_data.shape[0]}."
            )
            raise ValueError(msg)
        input_data = input_data.reshape(1, -1)

        outputs = await asyncio.to_thread(
            self._session.run,
            None,
            {
                "input": input_data,
                "state": self._state,
                "sr": self._sr_tensor,
            },
        )
        speech_prob = float(outputs[0].flat[0])  # type: ignore[attr-defined]
        new_state = np.array(outputs[1], dtype=np.float32)

        if self._use_state:
            self._state = new_state

        return speech_prob > self._speech_threshold
