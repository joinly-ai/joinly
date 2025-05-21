import asyncio
import logging

import click

from meeting_agent import client
from meeting_agent.server import SESSION_CONFIG, mcp
from meeting_agent.utils import configure_logging

logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "-n",
    "--participant-name",
    type=str,
    help="The meeting participant name.",
    default="Blaire",
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
    "--pulse-server/--no-pulse-server",
    help="Run a dedicated PulseAudio server. Expects a running PulseAudio server "
    "otherwise.",
    default=True,
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
    "--server/--client",
    help="Run the meeting agent as server or client. For --client, a meeting-url is "
    "required.",
    default=True,
)
@click.option(
    "-h",
    "--host",
    type=str,
    help="The host to bind the server to. Only applicable with --server.",
    default="127.0.0.1",
    callback=lambda ctx, _, val: val if ctx.params.get("server", True) else None,
)
@click.option(
    "-p",
    "--port",
    type=int,
    help="The port to bind the server to. Only applicable with --server.",
    default=8000,
    callback=lambda ctx, _, val: val if ctx.params.get("server", True) else None,
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
    default=None,
    type=str,
    required=False,
    envvar="MEETING_URL",
)
def cli(  # noqa: PLR0913
    *,
    server: bool,
    host: str,
    port: int,
    verbose: int,
    quiet: bool,
    logging_plain: bool,
    **ms_kwargs: dict,
) -> None:
    """Start the meeting session."""
    configure_logging(
        verbose=verbose,
        quiet=quiet,
        plain=logging_plain,
    )

    if not server and ms_kwargs.get("meeting_url") is None:
        msg = "The meeting URL is required when running as a client."
        raise click.BadParameter(
            msg,
            param_hint="MEETING_URL",
        )
    SESSION_CONFIG.update(ms_kwargs)

    if server:
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        asyncio.run(client.run())


if __name__ == "__main__":
    cli()
