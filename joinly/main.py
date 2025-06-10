import asyncio
import json
import logging
from typing import Any

import click
from dotenv import load_dotenv

from joinly import client
from joinly.server import mcp
from joinly.settings import Settings, set_settings
from joinly.utils.logging import configure_logging

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
    "--server/--client",
    help="Run joinly as server or client.",
    default=True,
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
    "-h",
    "--host",
    type=str,
    help="The host to bind the server to. Only applicable with --server.",
    default="127.0.0.1",
    show_default=True,
    envvar="JOINLY_SERVER_HOST",
)
@click.option(
    "-p",
    "--port",
    type=int,
    help="The port to bind the server to. Only applicable with --server.",
    default=8000,
    show_default=True,
    envvar="JOINLY_SERVER_PORT",
)
@click.option(
    "--model-name",
    type=str,
    help="The name of the model to use in the client and/or browser agent.",
    default="gpt-4o",
    show_default=True,
    envvar="JOINLY_MODEL_NAME",
)
@click.option(
    "--model-provider",
    type=str,
    help="The provider of the model to use in the client and/or browser agent. "
    "Automatically determined by the model name, "
    'but e.g. for Azure OpenAI use "azure_openai".',
    default=None,
    envvar="JOINLY_MODEL_PROVIDER",
)
@click.option(
    "--name-trigger",
    is_flag=True,
    help="Trigger the agent only when the name is mentioned in the transcript. "
    "Only applicable with --client. Note: it is recommended to change the name "
    "to a rather common name that has higher chance being transcribed.",
)
@click.option(
    "-m",
    "--meeting-provider",
    type=str,
    help="Meeting provider to use.",
    default="browser",
    show_default=True,
)
@click.option(
    "--vnc-server",
    is_flag=True,
    help="Enable VNC server for the meeting provider. "
    "Only applicable with --meeting-provider browser. ",
    default=False,
    show_default=True,
)
@click.option(
    "--vnc-server-port",
    type=int,
    help="Port for the VNC server. Only applicable with --vnc-server.",
    default=5900,
    show_default=True,
)
@click.option(
    "--browser-agent",
    type=str,
    help="Browser agent to use for the meeting provider. "
    'Defaults to no browser agent, options are: "playwright-mcp". '
    "Only applicable with --meeting-provider browser.",
    default=None,
    show_default=True,
    envvar="JOINLY_BROWSER_AGENT",
)
@click.option(
    "--vad",
    type=str,
    help='Voice Activity Detection service to use. Options are: "webrtc", "silero".',
    default="webrtc",
    show_default=True,
)
@click.option(
    "--stt",
    type=str,
    help='Speech-to-Text service to use. Options are: "whisper".',
    default="whisper",
    show_default=True,
)
@click.option(
    "--tts",
    type=str,
    help='Text-to-Speech service to use. Options are: "kokoro", "deepgram".',
    default="kokoro",
    show_default=True,
)
@click.option(
    "--meeting-provider-arg",
    "meeting_provider_args",
    multiple=True,
    metavar="KEY=VAL",
    callback=_parse_kv,
    help="Arguments for the meeting provider in the form of key=value. "
    "Can be specified multiple times.",
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
@click.option(
    "-q", "--quiet", is_flag=True, help="Suppress all but error and critical logging."
)
@click.option("--logging-plain", is_flag=True, help="Use plain logging format.")
@click.argument(
    "meeting-url",
    default=None,
    type=str,
    required=False,
    envvar="JOINLY_MEETING_URL",
)
def cli(  # noqa: PLR0913
    *,
    server: bool,
    host: str,
    port: int,
    model_name: str,
    model_provider: str | None,
    vnc_server: bool,
    vnc_server_port: int,
    browser_agent: str | None,
    name_trigger: bool,
    meeting_url: str | None,
    verbose: int,
    quiet: bool,
    logging_plain: bool,
    **cli_settings: dict[str, Any],
) -> None:
    """Start joinly MCP server or server + client to join meetings."""
    if cli_settings.get("meeting_provider") == "browser":
        if vnc_server:
            cli_settings["meeting_provider_args"] = cli_settings.get(
                "meeting_provider_args", {}
            )
            cli_settings["meeting_provider_args"]["vnc_server"] = True
            cli_settings["meeting_provider_args"]["vnc_server_port"] = vnc_server_port
        if browser_agent:
            cli_settings["meeting_provider_args"]["browser_agent"] = browser_agent
        if not cli_settings.get("meeting_provider_args", {}).get("browser_agent_args"):
            cli_settings["meeting_provider_args"]["browser_agent_args"] = {
                "model_name": model_name,
                "model_provider": model_provider,
            }

    settings = Settings(**cli_settings)  # type: ignore[arg-type]
    set_settings(settings)

    configure_logging(
        verbose=verbose,
        quiet=quiet,
        plain=logging_plain,
    )

    if server:
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        asyncio.run(
            client.run(
                meeting_url=meeting_url,
                model_name=model_name,
                model_provider=model_provider,
                name_trigger=name_trigger,
            )
        )


if __name__ == "__main__":
    cli()
