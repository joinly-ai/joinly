import asyncio
import json
import logging
from typing import Any

import click
from dotenv import load_dotenv

from joinly.server import mcp
from joinly.settings import Settings, set_settings
from joinly.utils.logging import configure_logging

logger = logging.getLogger(__name__)


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
    help="Run joinly as server or client. Default is server without a meeting URL "
    ", client otherwise.",
    default=None,
)
@click.option(
    "-n",
    "--name",
    type=str,
    help="The meeting participant name.",
    default="joinly",
    show_default=True,
    show_envvar=True,
    envvar="JOINLY_NAME",
)
@click.option(
    "--language",
    "--lang",
    type=str,
    help="The language to use for transcription and text-to-speech.",
    default="en",
    show_default=True,
    show_envvar=True,
    envvar="JOINLY_LANGUAGE",
)
@click.option(
    "--device",
    type=str,
    help="The device to use for the model. "
    "Defaults to 'cpu', but can be set to 'cuda' for GPU acceleration. "
    "Note that 'cuda' requires the extra cuda dependencies to be installed.",
    default="cpu",
    show_default=True,
    show_envvar=True,
    envvar="JOINLY_DEVICE",
)
@click.option(
    "-h",
    "--host",
    type=str,
    help="The host to bind the server to. Only applicable with --server.",
    default="127.0.0.1",
    show_default=True,
    show_envvar=True,
    envvar="JOINLY_SERVER_HOST",
)
@click.option(
    "-p",
    "--port",
    type=int,
    help="The port to bind the server to. Only applicable with --server.",
    default=8000,
    show_default=True,
    show_envvar=True,
    envvar="JOINLY_SERVER_PORT",
)
@click.option(
    "--llm-provider",
    "--model-provider",
    type=str,
    help="The provider of the LLM model to use in the client.",
    default="openai",
    show_default=True,
    show_envvar=True,
    envvar=["JOINLY_LLM_PROVIDER", "JOINLY_MODEL_PROVIDER"],
)
@click.option(
    "--llm-model",
    "--model-name",
    type=str,
    help="The name of the LLM model to use in the client.",
    default="gpt-4o",
    show_default=True,
    show_envvar=True,
    envvar=["JOINLY_LLM_MODEL", "JOINLY_MODEL_NAME"],
)
@click.option(
    "--env-file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to a .env file to load environment variables from.",
    default=None,
    show_default=True,
    is_eager=True,
    expose_value=False,
    callback=lambda _ctx, _param, value: load_dotenv(value),
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
    "--prompt-style",
    type=click.Choice(["dyadic", "mpc"], case_sensitive=False),
    help="The type of default prompt to use if no custom prompt is provided."
    "Options are 'dyadic' for one-on-one meetings or 'mpc' for group meetings.",
    default="mpc",
    show_default=True,
    show_envvar=True,
    envvar="JOINLY_PROMPT_STYLE",
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
    "--vad",
    type=str,
    help='Voice Activity Detection service to use. Options are: "webrtc", "silero".',
    default="silero",
    show_default=True,
    show_envvar=True,
    envvar="JOINLY_VAD",
)
@click.option(
    "--stt",
    type=str,
    help='Speech-to-Text service to use. Options are: "whisper" (local), "deepgram".',
    default="whisper",
    show_default=True,
    show_envvar=True,
    envvar="JOINLY_STT",
)
@click.option(
    "--tts",
    type=str,
    help='Text-to-Speech service to use. Options are: "kokoro" (local), '
    '"elevenlabs", "deepgram".',
    default="kokoro",
    show_default=True,
    show_envvar=True,
    envvar="JOINLY_TTS",
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
    default=1,
)
@click.option(
    "-q", "--quiet", is_flag=True, help="Suppress all but error and critical logging."
)
@click.option(
    "--logging-plain",
    is_flag=True,
    help="Use plain logging format.",
    show_envvar=True,
    envvar="JOINLY_LOGGING_PLAIN",
)
@click.argument(
    "meeting-url",
    default=None,
    type=str,
    required=False,
)
def cli(  # noqa: PLR0913
    *,
    server: bool | None,
    host: str,
    port: int,
    llm_provider: str,
    llm_model: str,
    vnc_server: bool,
    vnc_server_port: int,
    prompt: str | None,
    prompt_style: str,
    name_trigger: bool,
    meeting_url: str | None,
    verbose: int,
    quiet: bool,
    logging_plain: bool,
    **cli_settings: Any,  # noqa: ANN401
) -> None:
    """Start joinly MCP server or server + client to join meetings."""
    if cli_settings.get("meeting_provider") == "browser" and vnc_server:
        cli_settings["meeting_provider_args"] = cli_settings.get(
            "meeting_provider_args", {}
        )
        cli_settings["meeting_provider_args"]["vnc_server"] = True
        cli_settings["meeting_provider_args"]["vnc_server_port"] = vnc_server_port

    settings = Settings(**cli_settings)  # type: ignore[arg-type]
    set_settings(settings)

    configure_logging(
        verbose=verbose,
        quiet=quiet,
        plain=logging_plain,
    )

    if server is True or (server is None and meeting_url is None):
        mcp.run(transport="streamable-http", host=host, port=port, show_banner=False)
    else:
        import joinly_client

        if not meeting_url:
            msg = (
                "Meeting URL is required when running as a client. "
                "Please provide it as an argument."
            )
            raise click.UsageError(msg)
        asyncio.run(
            joinly_client.run(
                joinly_url=mcp,
                meeting_url=meeting_url,
                llm_provider=llm_provider,
                llm_model=llm_model,
                prompt=prompt,
                prompt_style=prompt_style,
                name=settings.name,
                name_trigger=name_trigger,
            )
        )


if __name__ == "__main__":
    cli()
