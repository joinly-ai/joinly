import asyncio
import fcntl
import logging
import os
import tempfile
from pathlib import Path
from typing import Self

logger = logging.getLogger(__name__)

_ENV_VAR = "VIRTUAL_AUDIO_SOURCE"


class VirtualMicrophone:
    """A class to create and unload a virtual microphone and play audio."""

    def __init__(
        self,
        *,
        sample_rate: int = 24000,
        frame_bits: int = 16,
        pipe_size: int = 2048,
        fifo_path: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize the VirtualMicrophone.

        Args:
            sample_rate: Sample rate for the audio.
            frame_bits: Number of bits per frame for the audio.
            pipe_size: Size of the pipe for the audio.
            fifo_path: Path to the FIFO file for audio input.
            env: Optional environment dictionary to set the audio source name.
        """
        self.sample_rate = sample_rate
        self.frame_bits = frame_bits
        self.pipe_size = pipe_size
        self.fifo_path = fifo_path
        self._env: dict[str, str] = env if env is not None else {}
        self._dir: tempfile.TemporaryDirectory[str] | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        """Set up the fifo file and input stream."""
        if self._writer is not None:
            msg = "Audio streamer already started"
            raise RuntimeError(msg)

        if self.fifo_path is None:
            self._dir = tempfile.TemporaryDirectory(prefix="virtmic_")
            self.fifo_path = Path(self._dir.name) / "fifo.wav"
        elif self.fifo_path.exists():
            msg = f"FIFO file already exists: {self.fifo_path}"
            logger.error(msg)
            raise RuntimeError(msg)

        logger.info("Creating FIFO file: %s", self.fifo_path)
        os.mkfifo(self.fifo_path, 0o600)
        self._env[_ENV_VAR] = str(self.fifo_path)

        logger.info("Setting up FIFO file for writing: %s", self.fifo_path)
        fd = os.open(self.fifo_path, os.O_WRONLY)
        fcntl.fcntl(fd, fcntl.F_SETPIPE_SZ, self.pipe_size)

        loop = asyncio.get_running_loop()
        transport, protocol = await loop.connect_write_pipe(
            asyncio.Protocol, os.fdopen(fd, "wb", buffering=0)
        )
        transport.set_write_buffer_limits(high=self.pipe_size, low=self.pipe_size // 2)
        self._writer = asyncio.StreamWriter(transport, protocol, None, loop)

        self._writer.write(_wav_header(self.sample_rate, 1, self.frame_bits))
        await self._writer.drain()

        logger.info("FIFO file created and opened for writing: %s", self.fifo_path)

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the audio stream and clean up resources."""
        if self._writer is not None:
            logger.info("Closing FIFO file: %s", self.fifo_path)
            await self._writer.drain()
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None

        if self._env.get(_ENV_VAR) == str(self.fifo_path):
            self._env.pop(_ENV_VAR)

        if self._dir is not None:
            logger.info("Cleaning up temporary directory: %s", self._dir.name)
            self._dir.cleanup()
            self._dir = None
        elif self.fifo_path is not None:
            logger.info("Removing FIFO file: %s", self.fifo_path)
            self.fifo_path.unlink(missing_ok=True)
            self.fifo_path = None

    async def write_frames(self, frames: bytes) -> None:
        """Write the incoming audio chunk.

        Args:
            frames (bytes): Audio data in f32le format to be processed.
        """
        if self._writer is None:
            msg = "Audio streamer not started"
            raise RuntimeError(msg)

        async with self._lock:
            logger.debug("Writing %d bytes to virtual microphone", len(frames))
            self._writer.write(frames)
            await self._writer.drain()


def _wav_header(rate: int, channels: int, bits: int) -> bytes:
    """Generate a unbounded PCM WAV header for the given parameters."""

    def _le(x: int, n: int) -> bytes:
        return x.to_bytes(n, "little")

    byte_rate = rate * channels * bits // 8
    block_align = channels * bits // 8
    return (
        b"RIFF"
        + _le(0xFFFFFFFF, 4)
        + b"WAVEfmt "
        + _le(16, 4)
        + _le(1, 2)
        + _le(channels, 2)
        + _le(rate, 4)
        + _le(byte_rate, 4)
        + _le(block_align, 2)
        + _le(bits, 2)
        + b"data"
        + _le(0xFFFFFFFF, 4)
    )
