import logging

LOGGING_TRACE = 5


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
                handlers=[RichHandler(rich_tracebacks=True)],
            )
        except ImportError:
            pass
        else:
            return

    logging.basicConfig(
        level=log_level,
        format="[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
