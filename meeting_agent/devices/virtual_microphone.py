import asyncio
import logging
import uuid
from typing import Self

from meeting_agent.devices.pulse_module_manager import PulseModuleManager

logger = logging.getLogger(__name__)


class VirtualMicrophone(PulseModuleManager):
    """A class to create and unload a virtual microphone and play audio."""

    def __init__(
        self, *, sample_rate: int = 24000, env: dict[str, str] | None = None
    ) -> None:
        """Initialize the VirtualMicrophone.

        Args:
            sample_rate: Sample rate for the audio.
            env: Optional environment dictionary to set the audio source name.
        """
        self.sample_rate = sample_rate
        self._env: dict[str, str] = env if env is not None else {}
        self._proc: asyncio.subprocess.Process | None = None
        self.sink_name: str | None = None
        self.source_name: str | None = None
        self._sink_module_id: int | None = None
        self._source_module_id: int | None = None
        self._write_silence_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Self:
        """Create the virtual audio sink.

        This method uses the `pactl` command to load the `module-null-sink` module
        with the specified sink name and properties. The sink is created in the
        PulseAudio server, allowing audio to be captured from it.

        Raises:
            RuntimeError: If the source creation fails.
        """
        if self._sink_module_id is not None:
            msg = "Audio sink already created"
            raise RuntimeError(msg)

        if self._source_module_id is not None:
            msg = "Audio source already created"
            raise RuntimeError(msg)

        if self._proc:
            msg = "Audio streamer already started"
            raise RuntimeError(msg)

        self.sink_name = f"virt.mic.{uuid.uuid4()}"
        self.source_name = f"{self.sink_name}.source"

        logger.info("Creating virtual audio sink: %s", self.sink_name)

        self._sink_module_id = await self._load_module(
            "module-null-sink",
            f"sink_name={self.sink_name}",
            "sink_properties=device.description=virt",
        )

        logger.info(
            "Creating virtual audio source: %s for sink: %s",
            self.source_name,
            self.sink_name,
        )

        self._source_module_id = await self._load_module(
            "module-remap-source",
            f"source_name={self.source_name}",
            f"master={self.sink_name}.monitor",
            "channels=1",
            "channel_map=mono",
            "source_properties=device.description=virt",
        )

        self._env["PULSE_SOURCE"] = self.source_name

        logger.info(
            "Created virtual audio source: %s (id: %d) and sink: %s (id: %d)",
            self.source_name,
            self._source_module_id,
            self.sink_name,
            self._sink_module_id,
        )

        logger.info("Starting audio stream into sink: %s", self.sink_name)

        # WIP: set PULSE_LATENCY_MSEC=30 ?
        # fmt: off
        """cmd = [
            "/usr/bin/ffmpeg",
            "-loglevel", "error",
            "-re",
            "-c:v", "none",
            "-c:a", "pcm_f32le",
            "-sample_fmt", "flt",
            "-f", "f32le",
            "-ar", str(self.sample_rate),
            "-ac", "1",
            "-i", "-",
            "-fflags", "+nobuffer+flush_packets",
            "-flags", "low_delay",
            "-avioflags", "direct",
            "-use_wallclock_as_timestamps", "1",
            "-probesize", "32",
            "-analyzeduration", "0",
            "-f", "pulse",
            self.sink_name,
        ]"""
        cmd = [
            "/usr/bin/ffmpeg",
            "-loglevel", "error",
            "-re",
            "-f", "f32le",
            "-ar", str(self.sample_rate),
            "-ac", "1",
            "-i", "-",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-probesize", "32",
            "-analyzeduration", "0",
            "-f", "pulse",
            self.sink_name,
        ]
        # fmt: on
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )

        logger.info(
            "Started audio streamer into sink: %s (sample_rate: %d)",
            self.sink_name,
            self.sample_rate,
        )

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Unload the sink module and stop audio stream."""
        if self._proc is None:
            logger.warning("Audio stream is not running, skipping stream close.")
        else:
            logger.info("Stopping audio stream into sink: %s", self.sink_name)

            self._proc.stdin.close()  # type: ignore[attr-defined]
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except TimeoutError:
                logger.warning("Audio stream process did not terminate, killing it.")
                self._proc.kill()
                await self._proc.wait()
            self._proc = None

            logger.info("Stopped audio stream into sink: %s", self.sink_name)

        if self._source_module_id is None:
            logger.warning("No source module ID found, skipping unload.")
        else:
            logger.info(
                "Unloading virtual audio source: %s (id: %s)",
                self.source_name,
                self._source_module_id,
            )

            await self._unload_module(self._source_module_id)

            logger.info(
                "Unloaded virtual audio source: %s (id: %s)",
                self.source_name,
                self._source_module_id,
            )

            if self._env.get("PULSE_SOURCE") == self.source_name:
                self._env.pop("PULSE_SOURCE")

            self.source_name = None
            self._source_module_id = None

        if self._sink_module_id is None:
            logger.warning("No sink module ID found, skipping unload.")
        else:
            logger.info(
                "Unloading virtual audio sink: %s (id: %s)",
                self.sink_name,
                self._sink_module_id,
            )

            await self._unload_module(self._sink_module_id)

            logger.info(
                "Unloaded virtual audio sink: %s (id: %s)",
                self.sink_name,
                self._sink_module_id,
            )

            self.sink_name = None
            self._sink_module_id = None

    # dont know, seems like bad practice and race condition
    async def _write_silence(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            if self._proc is None or self._proc.stdin is None:
                break
            self._proc.stdin.write(b"\x00" * 4096)

    async def write_frames(self, frames: bytes) -> None:
        """Write the incoming audio chunk.

        Args:
            frames (bytes): Audio data in f32le format to be processed.
        """
        if self._proc is None or self._proc.stdin is None:
            msg = "Audio streamer not started"
            raise RuntimeError(msg)

        logger.debug("Writing %d bytes to virtual microphone", len(frames))

        self._proc.stdin.write(frames)
        await self._proc.stdin.drain()
