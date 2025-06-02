import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Self

import numpy as np
import webrtcvad

from joinly.core import VAD, AudioReader
from joinly.types import VADWindow

logger = logging.getLogger(__name__)


class WebrtcVAD(VAD):
    """A class to detect speech in audio streams and chunk audio bytes using webrtcvad."""

    def __init__(
        self,
        *,
        aggressiveness: int = 2,
    ) -> None:
        self._aggressiveness = aggressiveness
        self._vad = webrtcvad.Vad(self._aggressiveness)
        self._sample_rate = 16000
        self._frame_duration = 30  # ms
        self._window_size_samples = int(self._sample_rate * self._frame_duration / 1000)
        # Note: Do not enforce self._byte_depth here, as we support both 2 and 4

    async def __aenter__(self) -> Self:
        logger.info("Initialized WebrtcVAD (SileroVAD wrapper)")
        return self

    async def __aexit__(self, *_exc: object) -> None:
        pass

    async def stream(self, reader: AudioReader) -> AsyncIterator[VADWindow]:
        if reader.sample_rate != self._sample_rate:
            raise ValueError(
                f"Expected sample rate {self._sample_rate}, got {reader.sample_rate}"
            )
        if reader.byte_depth not in (2, 4):
            raise ValueError(
                f"webrtcvad only supports 16-bit PCM (byte_depth=2), but got byte_depth={reader.byte_depth}."
            )

        idx: int = 0
        window_size: int = self._window_size_samples * reader.byte_depth
        chunk_dur: float = self._window_size_samples / self._sample_rate
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

                # --- Convert only for VAD, never for yield ---
                if reader.byte_depth == 4:
                    # float32 PCM [-1.0, 1.0] → int16 PCM [-32768, 32767]
                    arr32 = np.frombuffer(window_bytes, dtype=np.float32)
                    arr16 = np.clip(arr32 * 32767, -32768, 32767).astype(np.int16)
                    vad_bytes = arr16.tobytes()
                elif reader.byte_depth == 2:
                    vad_bytes = window_bytes
                else:
                    raise ValueError("Unsupported byte depth for VAD.")

                is_speech = self._vad.is_speech(vad_bytes, self._sample_rate)

                # Yield the *original* window_bytes in the format given by the reader
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
