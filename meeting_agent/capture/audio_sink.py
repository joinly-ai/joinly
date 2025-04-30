import asyncio
import logging
import uuid
from typing import Self

logger = logging.getLogger(__name__)


class AudioSink:
    """A class to create and unload a virtual audio null sink."""

    def __init__(
        self,
        sink_name: str | None = None,
    ) -> None:
        """Initialize the AudioSink with a random or provided sink name."""
        self.sink_name = sink_name or f"virt.{uuid.uuid4()}"
        self._module_id: str | None = None

    async def __aenter__(self) -> Self:
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

        self._module_id = stdout.decode().strip()
        logger.info(
            "Created virtual audio sink: %s (module_id: %s)",
            self.sink_name,
            self._module_id,
        )

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Unload the sink module."""
        if self._module_id is None:
            logger.warning("No module ID found, skipping unload.")
            return

        cmd = [
            "/usr/bin/pactl",
            "unload-module",
            self._module_id,
        ]
        unload_sink_proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await unload_sink_proc.communicate()
        if unload_sink_proc.returncode != 0:
            logger.warning("Failed to unload virtual audio sink: %s", stderr.decode())
        else:
            logger.info(
                "Unloaded virtual audio sink: %s (module_id: %s)",
                self.sink_name,
                self._module_id,
            )

        self._module_id = None
