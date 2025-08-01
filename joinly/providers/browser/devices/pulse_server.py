import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Self

from joinly.providers.browser.devices.pulse_module_manager import (
    PulseModuleManager,
)

logger = logging.getLogger(__name__)

_RUNTIME_ENV_VAR = "PULSE_RUNTIME_PATH"
_SERVER_ENV_VAR = "PULSE_SERVER"
_AUTOSPAWN_ENV_VAR = "PULSE_DISABLE_AUTOSPAWN"


class PulseServer(PulseModuleManager):
    """A class to start and stop a pulse server instance."""

    def __init__(
        self,
        *,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize the VirtualMicrophone.

        Args:
            env: Optional environment dictionary to set the audio server path.
        """
        self._env: dict[str, str] = env if env is not None else {}
        self.socket_path: Path | None = None
        self._dir: tempfile.TemporaryDirectory[str] | None = None
        self._proc: asyncio.subprocess.Process | None = None

    async def __aenter__(self) -> Self:
        """Start the audio server."""
        if self._proc is not None:
            msg = "Pulse server already started"
            raise RuntimeError(msg)

        self._dir = tempfile.TemporaryDirectory(prefix="pulseserver_")
        self.socket_path = Path(self._dir.name) / "native"
        self._env[_RUNTIME_ENV_VAR] = self._dir.name
        self._env[_SERVER_ENV_VAR] = f"unix:{self.socket_path}"
        self._env[_AUTOSPAWN_ENV_VAR] = "1"

        logger.debug("Starting PulseAudio server under %s", self._dir.name)
        self._proc = await asyncio.create_subprocess_exec(
            "/usr/bin/pulseaudio",
            "--daemonize=no",
            "--exit-idle-time=-1",
            "--file=/dev/null",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
            start_new_session=True,
        )

        try:
            await asyncio.wait_for(_wait_for_server(self.socket_path), timeout=5)
        except TimeoutError as e:
            msg = "PulseAudio server did not start in time"
            logger.error(msg)  # noqa: TRY400
            self._proc.kill()
            await self._proc.wait()
            self._dir.cleanup()
            raise RuntimeError(msg) from e

        logger.debug("PulseAudio server started")

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the audio server."""
        if self._proc is None or self._proc.returncode is not None:
            logger.warning("No PulseAudio server to stop")
        else:
            logger.debug("Stopping PulseAudio server")
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except TimeoutError:
                logger.warning("PulseAudio server did not stop in time")
                self._proc.kill()
                await self._proc.wait()
            self._proc = None
            self._env.pop(_RUNTIME_ENV_VAR, None)
            self._env.pop(_SERVER_ENV_VAR, None)
            self._env.pop(_AUTOSPAWN_ENV_VAR, None)
            logger.debug("PulseAudio server stopped")

        if self._dir is not None:
            self._dir.cleanup()
            logger.debug("Temporary directory removed: %s", self._dir.name)
            self._dir = None


async def _wait_for_server(path: Path) -> None:
    """Wait for the server to start."""
    while True:
        try:
            reader, writer = await asyncio.open_unix_connection(path)
        except (FileNotFoundError, ConnectionRefusedError):
            await asyncio.sleep(0.05)
        else:
            writer.close()
            await writer.wait_closed()
            return
