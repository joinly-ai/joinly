import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import Any

import click
from dotenv import load_dotenv
from fastmcp import Client, FastMCP

from joinly_client.agent import ConversationalAgent
from joinly_client.client import JoinlyClient

logger = logging.getLogger(__name__)

load_dotenv()


def _parse_kv(
    _ctx: click.Context, _param: click.Parameter, value: tuple[str]
) -> dict[str, object]:
    """Convert (--foo-arg key=value) repeated tuples to dict."""
    out: dict[str, object] = {}
    for item in value:
        try:
            k, v = item.split("=", 1)
        except ValueError as exc:
            msg = f"{item!r} is not of the form key=value"
            raise click.BadParameter(msg) from exc

        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


@click.command()
@click.option(
    "--joinly-url",
    type=str,
    help="The URL of the joinly server to connect to.",
    default="http://localhost:8000/mcp/",
    show_default=True,
    envvar="JOINLY_URL",
)
@click.option(
    "-n",
    "--name",
    type=str,
    help="The meeting participant name.",
    default="joinly",
    show_default=True,
    envvar="JOINLY_NAME",
)
@click.option(
    "--language",
    "--lang",
    type=str,
    help="The language to use for transcription and text-to-speech.",
    default="en",
    show_default=True,
    envvar="JOINLY_LANGUAGE",
)
@click.option(
    "--model-name",
    type=str,
    help="The name of the model to use in the client.",
    default="gpt-4o",
    show_default=True,
    envvar="JOINLY_MODEL_NAME",
)
@click.option(
    "--model-provider",
    type=str,
    help="The provider of the model to use in the client. "
    "Automatically determined by the model name, "
    'but e.g. for Azure OpenAI use "azure_openai".',
    default=None,
    envvar="JOINLY_MODEL_PROVIDER",
)
@click.option(
    "--prompt",
    type=str,
    help="System prompt to use for the model. If not provided, the default "
    "system prompt will be used.",
    default=None,
    envvar="JOINLY_PROMPT",
)
@click.option(
    "--mcp-config",
    type=str,
    help="Path to a JSON configuration file for additional MCP servers. "
    "The file should contain configuration like: "
    '\'{"mcpServers": {"remote": {"url": "https://example.com/mcp"}}}\'. '
    "See https://gofastmcp.com/clients/client for more details.",
    default=None,
)
@click.option(
    "--name-trigger",
    is_flag=True,
    help="Trigger the agent only when the name is mentioned in the transcript.",
)
@click.option(
    "--vad",
    type=str,
    help='Voice Activity Detection service to use. Options are: "silero", "webrtc".',
    default="silero",
    show_default=True,
)
@click.option(
    "--stt",
    type=str,
    help='Speech-to-Text service to use. Options are: "whisper" (local), "deepgram".',
    default="whisper",
    show_default=True,
)
@click.option(
    "--tts",
    type=str,
    help='Text-to-Speech service to use. Options are: "kokoro" (local), '
    '"elevenlabs", "deepgram".',
    default="kokoro",
    show_default=True,
)
@click.option(
    "--vad-arg",
    "vad_args",
    multiple=True,
    metavar="KEY=VAL",
    callback=_parse_kv,
    help="Arguments for the VAD service in the form of key=value. "
    "Can be specified multiple times.",
)
@click.option(
    "--stt-arg",
    "stt_args",
    multiple=True,
    metavar="KEY=VAL",
    callback=_parse_kv,
    help="Arguments for the STT service in the form of key=value. "
    "Can be specified multiple times.",
)
@click.option(
    "--tts-arg",
    "tts_args",
    multiple=True,
    metavar="KEY=VAL",
    callback=_parse_kv,
    help="Arguments for the TTS service in the form of key=value. "
    "Can be specified multiple times.",
)
@click.option(
    "--transcription-controller-arg",
    "transcription_controller_args",
    multiple=True,
    metavar="KEY=VAL",
    callback=_parse_kv,
    help="Arguments for the transcription controller in the form of key=value. "
    "Can be specified multiple times.",
)
@click.option(
    "--speech-controller-arg",
    "speech_controller_args",
    multiple=True,
    metavar="KEY=VAL",
    callback=_parse_kv,
    help="Arguments for the speech controller in the form of key=value. "
    "Can be specified multiple times.",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase logging verbosity (can be used multiple times).",
)
@click.argument(
    "meeting-url",
    type=str,
    required=True,
)
def cli(  # noqa: PLR0913
    *,
    joinly_url: str,
    name: str,
    model_name: str,
    model_provider: str | None,
    prompt: str | None,
    name_trigger: bool,
    mcp_config: str | None,
    meeting_url: str,
    verbose: int,
    **settings: dict[str, Any],
) -> None:
    """Run the joinly client."""
    from rich.logging import RichHandler

    log_level = logging.WARNING
    if verbose == 1:
        log_level = logging.INFO
    elif verbose == 2:  # noqa: PLR2004
        log_level = logging.DEBUG

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )

    mcp_config_dict: dict[str, Any] | None = None
    if mcp_config:
        try:
            with Path(mcp_config).open("r") as f:
                mcp_config_dict = json.load(f)
        except Exception:
            logger.exception("Failed to load MCP configuration file")
            mcp_config_dict = None

    try:
        asyncio.run(
            run(
                joinly_url=joinly_url,
                name=name,
                meeting_url=meeting_url,
                model_name=model_name,
                model_provider=model_provider,
                prompt=prompt,
                name_trigger=name_trigger,
                mcp_config=mcp_config_dict,
                settings=settings,
            )
        )
    except KeyboardInterrupt:
        logger.info("Exiting due to keyboard interrupt.")


async def run(  # noqa: PLR0913
    joinly_url: str | FastMCP,
    meeting_url: str,
    model_name: str,
    *,
    model_provider: str | None = None,
    prompt: str | None = None,
    name: str | None = None,
    name_trigger: bool = False,
    mcp_config: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> None:
    """Run the joinly client."""
    joinly_client = JoinlyClient(
        joinly_url,
        name=name,
        name_trigger=name_trigger,
        settings=settings,
    )
    mcp_client = Client(mcp_config) if mcp_config else None
    agent = ConversationalAgent(  # noqa: F841
        model_name, model_provider=model_provider, prompt=prompt
    )
    async with joinly_client, mcp_client or contextlib.nullcontext():
        await joinly_client.join_meeting(meeting_url)
        await asyncio.Event().wait()


if __name__ == "__main__":
    cli()
