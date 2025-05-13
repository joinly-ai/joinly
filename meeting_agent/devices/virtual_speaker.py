import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Self

from meeting_agent.devices.pulse_module_manager import PulseModuleManager

logger = logging.getLogger(__name__)


class VirtualSpeaker(PulseModuleManager, AsyncIterator[bytes]):
    """A class to create and unload a virtual audio null sink."""

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        frames_per_chunk: int = 512,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize the VirtualSpeaker.

        Args:
            sample_rate (int): The sample rate for the audio stream (default is 16000).
            frames_per_chunk (int): The number of frames per chunk (default is 512).
            env: Optional environment dictionary to set the sink name.
        """
        self.sample_rate = sample_rate
        self.frames_per_chunk = frames_per_chunk
        self._chunk_size = frames_per_chunk * 4
        self._env: dict[str, str] = env if env is not None else {}
        self._proc: asyncio.subprocess.Process | None = None
        self.sink_name: str | None = None
        self._monitor_name: str | None = None
        self._module_id: int | None = None

    async def __aenter__(self) -> Self:
        """Create the virtual audio sink and start capturing.

        Raises:
            RuntimeError: If the sink creation fails.
        """
        if self._module_id is not None:
            msg = "Audio sink already created"
            raise RuntimeError(msg)

        if self._proc:
            msg = "Audio streamer already started"
            raise RuntimeError(msg)

        self.sink_name = f"virt.{uuid.uuid4()}"
        self._monitor_name = f"{self.sink_name}.monitor"

        logger.info("Creating virtual audio sink: %s", self.sink_name)

        self._module_id = await self._load_module(
            "module-null-sink",
            f"sink_name={self.sink_name}",
            "sink_properties=device.description=virt",
        )

        self._env["PULSE_SINK"] = self.sink_name

        logger.info(
            "Created virtual audio sink: %s (id: %s)",
            self.sink_name,
            self._module_id,
        )

        logger.info("Starting audio stream from monitor: %s", self._monitor_name)

        # fmt: off
        cmd = [
            "/usr/bin/ffmpeg",
            "-loglevel", "error",
            "-f", "pulse",
            "-i", self._monitor_name,
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
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )

        logger.info(
            "Started audio streamer from monitor: %s "
            "(sample_rate: %d, frames_per_chunk: %d, chunk_size: %d)",
            self._monitor_name,
            self.sample_rate,
            self.frames_per_chunk,
            self._chunk_size,
        )

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Unload the sink module."""
        if self._proc is None:
            logger.warning("Audio stream is not running, skipping stream close.")
        else:
            logger.info("Stopping audio stream from monitor: %s", self._monitor_name)

            self._proc.stdin.write(b"q")  # type: ignore[attr-defined]
            await self._proc.stdin.drain()  # type: ignore[attr-defined]
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except TimeoutError:
                logger.warning("Audio stream process did not terminate, killing it.")
                self._proc.kill()
                await self._proc.wait()
            self._proc = None

            logger.info("Stopped audio stream from monitor: %s", self._monitor_name)

        if self._module_id is None:
            logger.warning("No module ID found, skipping unload.")
        else:
            logger.info(
                "Unloading virtual audio sink: %s (id: %s)",
                self.sink_name,
                self._module_id,
            )

            await self._unload_module(self._module_id)

            if self._env.get("PULSE_SINK") == self.sink_name:
                self._env.pop("PULSE_SINK")

            logger.info(
                "Unloaded virtual audio sink: %s (id: %s)",
                self.sink_name,
                self._module_id,
            )

            self.sink_name = None
            self._monitor_name = None
            self._module_id = None

    async def __anext__(self) -> bytes:
        """Return the next audio chunk from the stream.

        Returns:
            bytes: Audio data in f32le format with specified sample rate and chunk size.
        """
        if self._proc is None or self._proc.stdout is None:
            msg = "Audio streamer not started"
            raise RuntimeError(msg)

        return await self._proc.stdout.readexactly(self._chunk_size)
