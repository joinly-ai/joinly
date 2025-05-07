import asyncio
import logging
from typing import Self

logger = logging.getLogger(__name__)


class VirtualDisplay:
    """A class to create and dispose an Xvfb display."""

    def __init__(
        self,
        size: tuple[int, int] = (1280, 720),
        depth: int = 24,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize the VirtualDisplay.

        Args:
            size: The display width and height in pixels (default is 1280x720).
            depth: The color depth of the display (default is 24).
            env: Optional environment dictionary to set the display name.
        """
        self.size = size
        self.depth = depth
        self.display_name: str | None = None
        self._env: dict[str, str] = env if env is not None else {}
        self._proc: asyncio.subprocess.Process | None = None

    async def __aenter__(self) -> Self:
        """Start the Xvfb display."""
        if self._proc is not None:
            msg = "Xvfb already started"
            raise RuntimeError(msg)

        logger.info("Starting Xvfb display")

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
        )
        disp = (await self._proc.stdout.readline()).decode().strip()  # type: ignore[attr-defined]

        self.display_name = f":{disp}"
        self._env["DISPLAY"] = self.display_name

        logger.info(
            "Started Xvfb display: %s (size: %dx%d, depth: %d)",
            self.display_name,
            self.size[0],
            self.size[1],
            self.depth,
        )

        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the Xvfb display."""
        if self._proc is None:
            logger.warning("Xvfb is not started, skipping exit")
            return

        logger.info("Stopping Xvfb display: %s", self.display_name)

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

        logger.info("Stopped Xvfb display: %s", self.display_name)

        self.display_name = None
