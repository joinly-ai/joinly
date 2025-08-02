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
                level=logging.WARNING if not quiet else logging.ERROR,
                format="%(message)s",
                datefmt="[%X]",
                handlers=[RichHandler(rich_tracebacks=True)],
            )
            logging.getLogger("joinly").setLevel(log_level)
            logging.getLogger("joinly_client").setLevel(log_level)
        except ImportError:
            pass
        else:
            return

    logging.basicConfig(
        level=logging.WARNING if not quiet else logging.ERROR,
        format="[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("joinly").setLevel(log_level)
    logging.getLogger("joinly_client").setLevel(log_level)
