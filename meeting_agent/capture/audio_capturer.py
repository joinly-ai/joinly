import asyncio
import logging
import signal
import uuid
from collections.abc import AsyncIterator
from typing import Self

logger = logging.getLogger(__name__)


class AudioCapturer(AsyncIterator[bytes]):
    """A class to stream audio from a virtual sink to be processed as PCM data."""

    def __init__(
        self,
        sink_name: str | None = None,
        sample_rate: int = 16000,
        samples_per_chunk: int = 512,
    ) -> None:
        """Initialize the AudioCapturer with default virtual sink configuration."""
        self.sink_name = sink_name or f"virt.{uuid.uuid4()}"
        self.sample_rate = sample_rate
        self.samples_per_chunk = samples_per_chunk
        self._chunk_size = samples_per_chunk * 4
        self._sink_idx: str | None = None
        self._proc: asyncio.subprocess.Process | None = None

    async def __aenter__(self) -> Self:
        """Start the audio streamer."""
        await self._create_sink()
        await self._start_streaming()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the audio streamer and unload the sink module."""
        await self._stop_streaming()
        await self._teardown_sink()

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

    async def _create_sink(self) -> None:
        """Create the virtual audio sink.

        This method uses the `pactl` command to load the `module-null-sink` module
        with the specified sink name and properties. The sink is created in the
        PulseAudio server, allowing audio to be captured from it.

        Raises:
            RuntimeError: If the sink creation fails.
        """
        cmd = [
            "/usr/bin/pactl",
            "load-module",
            "module-null-sink",
            f"sink_name={self.sink_name}",
            "sink_properties=device.description=virt",
        ]

        load_sink_proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await load_sink_proc.communicate()
        if load_sink_proc.returncode != 0:
            msg = f"Failed to create virtual audio sink: {stderr.decode()}"
            logger.error(msg)
            raise RuntimeError(msg)

        self._sink_idx = stdout.decode().strip()

    async def _teardown_sink(self) -> None:
        """Unload the virtual audio sink module."""
        if self._sink_idx:
            cmd = [
                "/usr/bin/pactl",
                "unload-module",
                self._sink_idx,
            ]
            unload_sink_proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await unload_sink_proc.communicate()
            if unload_sink_proc.returncode != 0:
                logger.warning(
                    "Failed to unload virtual audio sink: %s", stderr.decode()
                )

            self._sink_idx = None

    async def _start_streaming(self) -> None:
        """Start the audio streaming process.

        Creates a virtual audio sink if not present and starts FFmpeg to capture
        and stream audio from the sink monitor.

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

    async def _stop_streaming(self) -> None:
        """Stop the audio streaming process.

        Terminates the FFmpeg subprocess and unloads the virtual audio sink.
        Sets the process and sink index to None after cleanup.
        """
        if self._proc:
            self._proc.send_signal(signal.SIGINT)
            await self._proc.wait()
        self._proc = None
