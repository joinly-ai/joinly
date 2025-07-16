import asyncio
import logging

from fastmcp.server.dependencies import get_context

LOGGING_TRACE = 5


class MCPLogger(logging.Handler):
    """Custom logging handler to use with FastMCP."""

    def __init__(self, level: int = logging.ERROR) -> None:
        """Initialize the MCPLogger."""
        super().__init__(level=level)
        self._tasks: set[asyncio.Task] = set()

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record."""
        if record.levelno < logging.ERROR:
            return

        try:
            ctx = get_context()
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return

        message = self.format(record)
        task = loop.create_task(ctx.error(message))
        task.add_done_callback(self._tasks.discard)
        self._tasks.add(task)


def configure_logging(verbose: int, *, quiet: bool, plain: bool) -> None:
    """Configure logging based on verbosity level."""
    log_level = logging.WARNING

    if quiet:
        log_level = logging.ERROR
    elif verbose == 1:
        log_level = logging.INFO
    elif verbose == 2:  # noqa: PLR2004
        log_level = logging.DEBUG
    elif verbose > 2:  # noqa: PLR2004
        log_level = LOGGING_TRACE

    logging.addLevelName(LOGGING_TRACE, "TRACE")

    if not plain:
        try:
            from rich.logging import RichHandler

            logging.basicConfig(
                level=log_level,
                format="%(message)s",
                datefmt="[%X]",
                handlers=[RichHandler(rich_tracebacks=True), MCPLogger()],
            )
        except ImportError:
            pass
        else:
            return

    logging.basicConfig(
        level=log_level,
        format="[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[MCPLogger()],
    )
