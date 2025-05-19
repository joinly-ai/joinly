import asyncio
import contextlib
import logging

import click

from meeting_agent import MeetingSession

logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "-n",
    "--participant-name",
    type=str,
    help="The meeting participant name.",
    default="Kevin",
)
@click.option(
    "--headless/--no-headless",
    help="Run the meeting session in headless mode.",
    default=True,
)
@click.option(
    "--vnc-server/--no-vnc-server",
    help="Run a VNC server to connect to. Only applicable with --headless.",
    default=False,
    callback=lambda ctx, _, val: val if ctx.params.get("headless", True) else False,
)
@click.option(
    "--vnc-server-port",
    type=int,
    help="The port for the VNC server. Only applicable with --vnc-server.",
    default=None,
    callback=lambda ctx, _, val: val if ctx.params.get("vnc_server", False) else None,
)
@click.option(
    "--browser-agent/--no-browser-agent",
    help="Use a browser agent to run the meeting session.",
    default=False,
)
@click.option(
    "--browser-agent-port",
    type=int,
    help="The port for the browser agent. Only applicable with --browser-agent.",
    default=None,
    callback=lambda ctx, _, val: val
    if ctx.params.get("browser_agent", False)
    else None,
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase logging verbosity (can be used multiple times).",
)
@click.option(
    "-q", "--quiet", is_flag=True, help="Suppress all but error and critical logging."
)
@click.option("--logging-plain", is_flag=True, help="Use plain logging format.")
@click.argument(
    "meeting-url",
    type=str,
    required=False,
    envvar="MEETING_URL",
)
def cli(  # noqa: PLR0913
    meeting_url: str | None,
    participant_name: str,
    *,
    headless: bool,
    vnc_server: bool,
    vnc_server_port: int | None,
    browser_agent: bool,
    browser_agent_port: int | None,
    verbose: int,
    quiet: bool,
    logging_plain: bool,
) -> None:
    """Start the meeting session."""
    configure_logging(verbose, quiet=quiet, plain=logging_plain)

    if meeting_url is None:
        from meeting_agent.server import mcp

        mcp.run(transport="streamable-http")
    else:
        asyncio.run(
            run_meeting_session(
                meeting_url,
                participant_name,
                headless=headless,
                use_vnc_server=vnc_server,
                vnc_server_port=vnc_server_port,
                use_browser_agent=browser_agent,
                browser_agent_port=browser_agent_port,
            )
        )


def configure_logging(verbose: int, *, quiet: bool, plain: bool) -> None:
    """Configure logging based on verbosity level."""
    log_level = logging.WARNING

    if quiet:
        log_level = logging.ERROR
    elif verbose == 1:
        log_level = logging.INFO
    elif verbose >= 2:  # noqa: PLR2004
        log_level = logging.DEBUG

    if not plain:
        with contextlib.suppress(ImportError):
            from rich.logging import RichHandler

            logging.basicConfig(
                level=log_level,
                format="%(message)s",
                datefmt="[%X]",
                handlers=[RichHandler(rich_tracebacks=True)],
            )
            return

    logging.basicConfig(
        level=log_level,
        format="[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def run_meeting_session(  # noqa: PLR0913
    meeting_url: str,
    participant_name: str,
    *,
    headless: bool,
    use_vnc_server: bool = False,
    vnc_server_port: int | None = None,
    use_browser_agent: bool = False,
    browser_agent_port: int | None = None,
) -> None:
    """Run the meeting session until receiving a cancellation signal."""
    ms = MeetingSession(
        headless=headless,
        use_vnc_server=use_vnc_server,
        vnc_server_port=vnc_server_port,
        use_browser_agent=use_browser_agent,
        browser_agent_port=browser_agent_port,
    )

    async def _on_transcription(event: str, text: str) -> None:
        if event == "chunk":
            logger.info("Transcription: %s", text)
            await ms.speak_text(text, wait=False, interrupt=False)

    ms.add_transcription_listener(_on_transcription)

    joined = False
    async with ms:
        try:
            await ms.join_meeting(
                meeting_url=meeting_url,
                participant_name=participant_name,
            )
            joined = True

            await asyncio.Event().wait()
        except asyncio.CancelledError:
            logger.info("Meeting session cancelled")
            if joined:
                with contextlib.suppress(Exception):
                    await ms.leave_meeting()
            raise


if __name__ == "__main__":
    cli()
