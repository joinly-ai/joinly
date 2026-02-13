import asyncio
import logging
from typing import Self

logger = logging.getLogger(__name__)

_ENV_VAR = "DBUS_SESSION_BUS_ADDRESS"


class DbusSession:
    """Manage a private D-Bus session daemon.

    Launches ``dbus-daemon --session`` and exposes the bus address via the
    shared *env* dictionary so that later services (Xvfb, Chromium) can
    connect to it.
    """

    def __init__(self, *, env: dict[str, str] | None = None) -> None:
        """Initialize the D-Bus session manager.

        Args:
            env: Optional environment dictionary to set the bus address.
        """
        self._env: dict[str, str] = env if env is not None else {}
        self._proc: asyncio.subprocess.Process | None = None

    async def __aenter__(self) -> Self:
        """Start the D-Bus session daemon."""
        if self._proc is not None:
            msg = "D-Bus session daemon already started"
            raise RuntimeError(msg)

        logger.debug("Starting D-Bus session daemon")

        self._proc = await asyncio.create_subprocess_exec(
            "dbus-daemon",
            "--session",
            "--print-address",
            "--nofork",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=self._env,
            start_new_session=True,
        )

        try:
            line = await asyncio.wait_for(
                self._proc.stdout.readline(),  # type: ignore[union-attr]
                timeout=5,
            )
        except TimeoutError as e:
            msg = "D-Bus session daemon did not print address in time"
            logger.error(msg)  # noqa: TRY400
            self._proc.kill()
            await self._proc.wait()
            raise RuntimeError(msg) from e

        address = line.decode().strip()
        if not address:
            msg = "D-Bus session daemon exited without printing an address"
            self._proc.kill()
            await self._proc.wait()
            raise RuntimeError(msg)

        self._env[_ENV_VAR] = address
        logger.debug("D-Bus session daemon started: %s", address)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the D-Bus session daemon."""
        if self._proc is None or self._proc.returncode is not None:
            logger.warning("No D-Bus session daemon to stop")
        else:
            logger.debug("Stopping D-Bus session daemon")
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except TimeoutError:
                logger.warning("D-Bus session daemon did not stop in time")
                self._proc.kill()
                await self._proc.wait()
            logger.debug("D-Bus session daemon stopped")

        self._proc = None
        self._env.pop(_ENV_VAR, None)
