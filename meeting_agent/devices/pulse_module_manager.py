import asyncio
import logging

logger = logging.getLogger(__name__)


class PulseModuleManager:
    """A class to load and unload pulse modules via pactl."""

    async def _load_module(
        self, *cmd_args: str, env: dict[str, str] | None = None
    ) -> int:
        """Load a pulse module using pactl.

        Args:
            cmd_args: Arguments to pass to the pactl command.
            env: Optional environment variables to set for the command.

        Returns:
            The module id.
        """
        cmd = ["/usr/bin/pactl", "load-module", *cmd_args]
        load_sink_proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await load_sink_proc.communicate()
        if load_sink_proc.returncode != 0:
            msg = f"Failed to load pulse module: {stderr.decode()}"
            logger.error(msg)
            raise RuntimeError(msg)

        return int(stdout.decode().strip())

    async def _unload_module(
        self, module_id: int, env: dict[str, str] | None = None
    ) -> None:
        """Unload a pulse module using pactl.

        Args:
            module_id: The ID of the module to unload.
            env: Optional environment variables to set for the command.

        Raises:
            RuntimeError: If the module unload fails.
        """
        cmd = ["/usr/bin/pactl", "unload-module", str(module_id)]
        unload_sink_proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await unload_sink_proc.communicate()
        if unload_sink_proc.returncode != 0:
            msg = f"Failed to unload pulse module: {stderr.decode()}"
            logger.error(msg)
            raise RuntimeError(msg)
