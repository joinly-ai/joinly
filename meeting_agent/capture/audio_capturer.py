import asyncio
import logging
import signal
from collections.abc import AsyncIterator
from typing import Self

logger = logging.getLogger(__name__)


class AudioCapturer(AsyncIterator[bytes]):
    """A class to stream audio from a virtual sink to be processed as PCM data."""

    def __init__(
        self,
        sink_name: str,
        sample_rate: int = 16000,
        frames_per_chunk: int = 512,
    ) -> None:
        """Initialize the AudioCapturer.

        Args:
            sink_name (str): The name of the virtual audio sink.
            sample_rate (int): The sample rate for the audio stream (default is 16000).
            frames_per_chunk (int): The number of frames per chunk (default is 512).
        """
        self.sink_name = sink_name
        self.sample_rate = sample_rate
        self.frames_per_chunk = frames_per_chunk
        self._chunk_size = frames_per_chunk * 4
        self._proc: asyncio.subprocess.Process | None = None

    async def __aenter__(self) -> Self:
        """Start the audio streaming process.

        Creates a raw audio input stream from the virtual audio sink monitor
        using the configured sample rate and frame size.

        Raises:
            RuntimeError: If the audio streamer has already been started.
        """
        if self._proc:
            msg = "Audio streamer already started"
            raise RuntimeError(msg)

        # fmt: off
        cmd = [
            "/usr/bin/ffmpeg",
            "-loglevel", "error",
            "-f", "pulse",
            "-i", f"{self.sink_name}.monitor",
            "-ac", "1",
            "-ar", str(self.sample_rate),
            "-sample_fmt", "flt",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-probesize", "32",
            "-analyzeduration", "0",
            "-f", "f32le",
            "-",
        ]
        # fmt: on
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
        )

        logger.info(
            "Started audio streamer from sink: %s "
            "(sample_rate: %d, frames_per_chunk: %d, chunk_size: %d)",
            self.sink_name,
            self.sample_rate,
            self.frames_per_chunk,
            self._chunk_size,
        )

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the audio streaming process.

        Terminates the FFmpeg subprocess and sets the process to None after cleanup.
        """
        if self._proc is None:
            logger.warning("Audio stream is not running, skipping stream close.")
            return

        self._proc.send_signal(signal.SIGINT)
        await self._proc.wait()
        self._proc = None

        logger.info("Stopped audio stream from sink: %s", self.sink_name)

    async def __anext__(self) -> bytes:
        """Return the next audio chunk from the stream.

        Returns:
            bytes: Audio data in f32le format with specified sample rate and chunk size.
        """
        if self._proc is None:
            msg = "Audio streamer not started"
            raise RuntimeError(msg)

        if self._proc.stdout is None:
            msg = "Audio streamer process has no stdout"
            raise RuntimeError(msg)

        return await self._proc.stdout.readexactly(self._chunk_size)
