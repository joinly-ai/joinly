import asyncio
import logging
import re
from typing import Self

logger = logging.getLogger(__name__)

_VNC_PORT_RE = re.compile(r"PORT=(\d+)")


class VirtualDisplay:
    """A class to create and dispose an Xvfb display."""

    def __init__(
        self,
        *,
        env: dict[str, str] | None = None,
        size: tuple[int, int] = (1280, 720),
        depth: int = 24,
        use_vnc_server: bool = False,
        vnc_port: int | None = None,
    ) -> None:
        """Initialize the VirtualDisplay.

        Args:
            env: Optional environment dictionary to set the display name.
            size: The display width and height in pixels (default is 1280x720).
            depth: The color depth of the display (default is 24).
            use_vnc_server: Whether to use a VNC server (default is False).
            vnc_port: The port for the VNC server (default is None).
        """
        self._env: dict[str, str] = env if env is not None else {}
        self.size = size
        self.depth = depth
        self.display_name: str | None = None
        self.use_vnc_server = use_vnc_server
        self.vnc_port = vnc_port
        self._vnc_port = vnc_port
        self._proc: asyncio.subprocess.Process | None = None
        self._vnc_proc: asyncio.subprocess.Process | None = None

    async def __aenter__(self) -> Self:
        """Start the Xvfb display."""
        if self._proc is not None:
            msg = "Xvfb already started"
            raise RuntimeError(msg)

        logger.debug("Starting Xvfb display")

        self._env["XDG_SESSION_TYPE"] = "x11"
        self._env.pop("WAYLAND_DISPLAY", None)

        # fmt: off
        cmd = [
            "/usr/bin/Xvfb",
            "-displayfd", "1",
            "-screen", "0", f"{self.size[0]}x{self.size[1]}x{self.depth}",
            "-nolisten", "tcp",
        ]
        # fmt: on

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=self._env,
            start_new_session=True,
        )
        disp = (await self._proc.stdout.readline()).decode().strip()  # type: ignore[attr-defined]

        self.display_name = f":{disp}"
        self._env["DISPLAY"] = self.display_name

        logger.debug(
            "Started Xvfb display: %s (size: %dx%d, depth: %d)",
            self.display_name,
            self.size[0],
            self.size[1],
            self.depth,
        )

        if self.use_vnc_server:
            cmd = [
                "/usr/bin/x11vnc",
                "-display",
                self.display_name,
                "-forever",
                "-nopw",
                "-shared",
            ]
            if self.vnc_port is not None:
                cmd.extend(["-rfbport", str(self.vnc_port)])

            self._vnc_proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
                start_new_session=True,
            )
            if self._vnc_port is None:
                while line := await self._vnc_proc.stdout.readline():  # type: ignore[attr-defined]
                    m = _VNC_PORT_RE.search(line.decode())
                    if m:
                        self._vnc_port = int(m.group(1))
                        break
                else:
                    logger.warning(
                        "Could not find VNC port in stdout, terminating VNC server"
                    )
                    self._vnc_proc.terminate()

            if self._vnc_port is not None:
                logger.info("Started VNC server on port: %s", self._vnc_port)

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the Xvfb display."""
        if self._proc is None:
            logger.warning("Xvfb is not started, skipping exit")
            return

        logger.debug("Stopping Xvfb display: %s", self.display_name)

        if self._proc.returncode is None:
            self._proc.terminate()
        try:
            await asyncio.wait_for(self._proc.wait(), 5)
        except TimeoutError:
            logger.warning(
                "Xvfb display %s did not stop in time, killing it", self.display_name
            )
            self._proc.kill()
            await self._proc.wait()
        self._proc = None

        if self._env.get("DISPLAY") == self.display_name:
            self._env.pop("DISPLAY")

        logger.debug("Stopped Xvfb display: %s", self.display_name)
        self.display_name = None

        if self._vnc_proc is not None:
            logger.debug("Stopping VNC server on port: %s", self._vnc_port)
            if self._vnc_proc.returncode is None:
                self._vnc_proc.terminate()
            try:
                await asyncio.wait_for(self._vnc_proc.wait(), 5)
            except TimeoutError:
                logger.warning(
                    "VNC server on port %s did not stop in time, killing it",
                    self._vnc_port,
                )
                self._vnc_proc.kill()
                await self._vnc_proc.wait()
            logger.debug("Stopped VNC server on port: %s", self._vnc_port)
            self._vnc_proc = None
            self._vnc_port = None
