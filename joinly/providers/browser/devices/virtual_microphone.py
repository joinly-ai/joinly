import asyncio
import contextlib
import fcntl
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Self

from joinly.core import AudioWriter
from joinly.providers.browser.devices.pulse_module_manager import (
    PulseModuleManager,
)
from joinly.utils.logging import LOGGING_TRACE

logger = logging.getLogger(__name__)

_ENV_VAR = "PULSE_SOURCE"


class VirtualMicrophone(PulseModuleManager, AudioWriter):
    """A class to create and unload a virtual microphone and play audio."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        sample_rate: int = 24000,
        pipe_size: int = 1920,
        fifo_path: Path | None = None,
        source_name: str | None = None,
        chunk_ms: int = 10,
        queue_size: int = 2,
        max_missed_chunks: int = 10,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize the VirtualMicrophone.

        Args:
            sample_rate: Sample rate for the audio.
            pipe_size: Size of the pipe for the audio.
            fifo_path: Path to the FIFO file for audio input.
            source_name: Name of the source.
            chunk_ms: Size of the audio chunk in milliseconds.
            queue_size: Size of the audio queue.
            max_missed_chunks: Maximum number of missed chunks before adjusting the
                pacing.
            env: Optional environment dictionary to set the audio source name.
        """
        self.sample_rate = sample_rate
        self.pipe_size = pipe_size
        self.fifo_path = fifo_path
        self.source_name: str = (
            source_name if source_name is not None else f"virtmic.{uuid.uuid4()}"
        )
        self.byte_depth = 4  # float32le
        self.chunk_size = int(sample_rate * chunk_ms / 1000) * self.byte_depth
        self.chunk_ms = self.chunk_size / (self.byte_depth * self.sample_rate) * 1000
        self.queue_size = queue_size
        self.max_missed_chunks = max_missed_chunks
        self._env: dict[str, str] = env if env is not None else {}
        self._dir: tempfile.TemporaryDirectory[str] | None = None
        self._module_id: int | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._queue: asyncio.Queue[bytes] | None = None
        self._pace_task: asyncio.Task | None = None

    async def __aenter__(self) -> Self:
        """Set up the fifo file and input stream."""
        if self._module_id is not None:
            msg = "Audio sink already created"
            raise RuntimeError(msg)

        if self._writer is not None or self._pace_task is not None:
            msg = "Audio streamer already started"
            raise RuntimeError(msg)

        if self.fifo_path is None:
            self._dir = tempfile.TemporaryDirectory(prefix="virtmic_")
            self.fifo_path = Path(self._dir.name) / "fifo.pcm"
        elif self.fifo_path.exists():
            msg = f"FIFO file already exists: {self.fifo_path}"
            logger.error(msg)
            raise RuntimeError(msg)

        logger.info("Creating virtual audio source: %s", self.source_name)
        self._module_id = await self._load_module(
            "module-pipe-source",
            f"source_name={self.source_name}",
            f"file={self.fifo_path}",
            f"rate={self.sample_rate}",
            "format=float32le",
            "channels=1",
            env=self._env,
        )
        logger.info(
            "Created virtual audio source: %s (id: %s)",
            self.source_name,
            self._module_id,
        )

        logger.info("Setting up FIFO file for writing: %s", self.fifo_path)
        fd = os.open(self.fifo_path, os.O_WRONLY)
        fcntl.fcntl(fd, fcntl.F_SETPIPE_SZ, self.pipe_size)

        loop = asyncio.get_running_loop()
        transport, protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, os.fdopen(fd, "wb", buffering=0)
        )
        transport.set_write_buffer_limits(high=self.pipe_size, low=self.pipe_size // 2)
        self._writer = asyncio.StreamWriter(transport, protocol, None, loop)
        self._queue = asyncio.Queue(maxsize=self.queue_size)
        self._pace_task = asyncio.create_task(self._pace_loop())

        self._env[_ENV_VAR] = self.source_name

        logger.info(
            "Virtual microphone is ready (source: %s, id: %s, fifo: %s, rate: %s)",
            self.source_name,
            self._module_id,
            self.fifo_path,
            self.sample_rate,
        )

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the audio stream and clean up resources."""
        if self._pace_task is not None:
            self._pace_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pace_task
            self._pace_task = None

        if self._queue is not None:
            while not self._queue.empty():
                chunk = self._queue.get_nowait()
                logger.warning("Canceled writing of %d bytes", len(chunk))
                self._queue.task_done()
            self._queue = None

        if self._writer is None:
            logger.warning("No fifo file to close")
        else:
            logger.info("Closing FIFO file: %s", self.fifo_path)
            with contextlib.suppress(Exception):
                self._writer.transport.close()
            self._writer = None

        if self._module_id is None:
            logger.warning("No module ID found, skipping unload.")
        else:
            logger.info(
                "Unloading virtual audio source: %s (id: %s)",
                self.source_name,
                self._module_id,
            )

            await self._unload_module(self._module_id, env=self._env)

            if self._env.get(_ENV_VAR) == self.source_name:
                self._env.pop(_ENV_VAR)

            logger.info(
                "Unloaded virtual audio source: %s (id: %s)",
                self.source_name,
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

    async def write(self, pcm: bytes) -> None:
        """Write the incoming audio chunk.

        Args:
            pcm (bytes): Audio data to be written.
        """
        if self._queue is None:
            msg = "Audio streamer not started"
            raise RuntimeError(msg)

        view = memoryview(pcm)
        while len(view) >= self.chunk_size:
            logger.log(
                LOGGING_TRACE,
                "Queueing %d bytes to virtual microphone",
                self.chunk_size,
            )
            await self._queue.put(bytes(view[: self.chunk_size]))
            view = view[self.chunk_size :]

        if view:
            pad_len = self.chunk_size - len(view)
            logger.log(
                LOGGING_TRACE,
                "Queueing %d bytes with %d bytes (total %d) of padding to "
                "virtual microphone",
                len(view),
                pad_len,
                self.chunk_size,
            )
            await self._queue.put(bytes(view) + b"\x00" * pad_len)

    async def _pace_loop(self) -> None:
        """Pace the audio stream."""
        if self._writer is None or self._queue is None:
            msg = "Audio streamer not started"
            raise RuntimeError(msg)

        loop = asyncio.get_running_loop()
        silence = b"\x00" * self.chunk_size
        period = self.chunk_ms / 1000
        next_deadline = loop.time() + period

        while True:
            now = loop.time()
            if now < next_deadline:
                await asyncio.sleep(next_deadline - now)
            else:
                missed = (now - next_deadline) / period
                if missed >= self.max_missed_chunks:
                    logger.warning(
                        "Missed %d pacing intervals, adjusting next deadline",
                        int(missed),
                    )
                    next_deadline = now
            next_deadline += period

            try:
                chunk = self._queue.get_nowait()
                logger.log(
                    LOGGING_TRACE, "Writing %d bytes to virtual microphone", len(chunk)
                )
            except asyncio.QueueEmpty:
                chunk = silence
                logger.log(
                    LOGGING_TRACE,
                    "Writing %d bytes of silence to virtual microphone",
                    len(chunk),
                )

            self._writer.write(chunk)
            await self._writer.drain()

            if chunk is not silence:
                self._queue.task_done()
