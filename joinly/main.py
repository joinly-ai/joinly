import asyncio
import logging

import click
from dotenv import load_dotenv

from joinly import client
from joinly.server import mcp
from joinly.utils import configure_logging

logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--server/--client",
    help="Run the meeting agent as server or client.",
    default=True,
)
@click.option(
    "-h",
    "--host",
    type=str,
    help="The host to bind the server to. Only applicable with --server.",
    default="127.0.0.1",
)
@click.option(
    "-p",
    "--port",
    type=int,
    help="The port to bind the server to. Only applicable with --server.",
    default=8000,
)
@click.option(
    "-n",
    "--participant-name",
    type=str,
    help="The meeting participant name.",
    default="joinly",
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
    participant_name: str,
    meeting_url: str | None = None,
    verbose: int,
    quiet: bool,
    logging_plain: bool,
) -> None:
    """Start the meeting session."""
    load_dotenv()

    configure_logging(
        verbose=verbose,
        quiet=quiet,
        plain=logging_plain,
    )

    if server:
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        asyncio.run(client.run(meeting_url, participant_name=participant_name))


if __name__ == "__main__":
    cli()
