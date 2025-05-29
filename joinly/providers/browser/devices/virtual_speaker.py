import asyncio
import fcntl
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Self

from joinly.core import AudioReader
from joinly.providers.browser.devices.pulse_module_manager import (
    PulseModuleManager,
)

logger = logging.getLogger(__name__)

_ENV_VAR = "PULSE_SINK"


class VirtualSpeaker(PulseModuleManager, AudioReader):
    """A class to create and unload a virtual audio null sink."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        sample_rate: int = 16000,
        frames_per_chunk: int = 512,
        pipe_size: int = 4096,
        fifo_path: Path | None = None,
        sink_name: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize the VirtualSpeaker.

        Args:
            sample_rate (int): The sample rate for the audio stream (default is 16000).
            frames_per_chunk (int): The number of frames per chunk (default is 512).
            pipe_size (int): The size of the pipe for audio streaming (default is 4096).
            fifo_path (Path | None): The path to the FIFO file (default is None).
            sink_name (str | None): The name of the sink (default is None).
            env: Optional environment dictionary to set the sink name.
        """
        self.sample_rate = sample_rate
        self.frames_per_chunk = frames_per_chunk
        self.pipe_size = pipe_size
        self.fifo_path = fifo_path
        self.sink_name: str = (
            sink_name if sink_name is not None else f"virt.{uuid.uuid4()}"
        )
        self.byte_depth = 4  # f32le
        self.chunk_size = frames_per_chunk * self.byte_depth
        self._env: dict[str, str] = env if env is not None else {}
        self._dir: tempfile.TemporaryDirectory[str] | None = None
        self._module_id: int | None = None
        self._reader: asyncio.StreamReader | None = None

    async def __aenter__(self) -> Self:
        """Create the virtual audio sink and start capturing.

        Raises:
            RuntimeError: If the sink creation fails.
        """
        if self._module_id is not None:
            msg = "Audio sink already created"
            raise RuntimeError(msg)

        if self._reader is not None:
            msg = "Audio reader already started"
            raise RuntimeError(msg)

        if self.fifo_path is None:
            self._dir = tempfile.TemporaryDirectory(prefix="virtsink_")
            self.fifo_path = Path(self._dir.name) / "fifo.pcm"
        elif self.fifo_path.exists():
            msg = f"FIFO file already exists: {self.fifo_path}"
            logger.error(msg)
            raise RuntimeError(msg)

        logger.info("Creating FIFO file: %s", self.fifo_path)
        os.mkfifo(self.fifo_path, 0o600)

        logger.info("Creating virtual audio sink: %s", self.sink_name)
        self._module_id = await self._load_module(
            "module-pipe-sink",
            f"sink_name={self.sink_name}",
            f"file={self.fifo_path}",
            f"rate={self.sample_rate}",
            "format=float32le",
            "channels=1",
            "use_system_clock_for_timing=yes",
            env=self._env,
        )
        logger.info(
            "Created virtual audio sink: %s (id: %s)",
            self.sink_name,
            self._module_id,
        )

        logger.info("Setting up FIFO file for reading: %s", self.fifo_path)
        fd = os.open(self.fifo_path, os.O_RDWR | os.O_NONBLOCK)
        fcntl.fcntl(fd, fcntl.F_SETPIPE_SZ, self.pipe_size)

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        loop = asyncio.get_running_loop()
        await loop.connect_read_pipe(lambda: protocol, os.fdopen(fd, "rb", buffering=0))
        self._reader = reader

        self._env[_ENV_VAR] = self.sink_name

        logger.info(
            "Virtual speaker is ready (sink: %s, id: %s, fifo: %s, rate: %s)",
            self.sink_name,
            self._module_id,
            self.fifo_path,
            self.sample_rate,
        )

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Unload the sink module."""
        if self._reader is None:
            logger.warning("No FIFO file to close")
        else:
            logger.info("Closing FIFO file: %s", self.fifo_path)
            self._reader.feed_eof()
            self._reader = None

        if self._module_id is None:
            logger.warning("No module ID found, skipping unload.")
        else:
            logger.info(
                "Unloading virtual audio sink: %s (id: %s)",
                self.sink_name,
                self._module_id,
            )

            await self._unload_module(self._module_id, env=self._env)

            if self._env.get(_ENV_VAR) == self.sink_name:
                self._env.pop(_ENV_VAR)

            logger.info(
                "Unloaded virtual audio sink: %s (id: %s)",
                self.sink_name,
                self._module_id,
            )
            self._module_id = None

        if self._dir is not None:
            self._dir.cleanup()
            logger.info("Temporary directory removed: %s", self._dir.name)
            self._dir = None
        elif self.fifo_path is not None:
            self.fifo_path.unlink()
            logger.info("FIFO file removed: %s", self.fifo_path)
            self.fifo_path = None
        else:
            logger.warning("No FIFO file to remove")

    async def read(self) -> bytes:
        """Return the next audio chunk from the stream.

        Returns:
            bytes: Audio data in f32le format with specified sample rate and chunk size.
        """
        if self._reader is None:
            msg = "Audio reader not started"
            raise RuntimeError(msg)

        try:
            return await self._reader.readexactly(self.chunk_size)
        except asyncio.IncompleteReadError as exc:
            raise StopAsyncIteration from exc
