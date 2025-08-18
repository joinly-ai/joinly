import asyncio
import json
import logging
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import click
from dotenv import load_dotenv
from fastmcp import Client, FastMCP

from joinly_client.agent import ConversationalToolAgent
from joinly_client.client import JoinlyClient
from joinly_client.types import McpClientConfig, TranscriptSegment
from joinly_client.utils import get_llm, get_prompt, load_tools

logger = logging.getLogger(__name__)


def _parse_kv(
    _ctx: click.Context, _param: click.Parameter, value: tuple[str]
) -> dict[str, object] | None:
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
    return out or None


@click.command()
@click.option(
    "--joinly-url",
    type=str,
    help="The URL of the joinly server to connect to.",
    default="http://localhost:8000/mcp/",
    show_default=True,
    show_envvar=True,
    envvar="JOINLY_URL",
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
    "--prompt-file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to a text file containing the system prompt.",
    default=None,
    show_default=True,
    envvar="JOINLY_PROMPT_FILE",
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
    "--language",
    "--lang",
    type=str,
    help="The language to use for transcription and text-to-speech.",
    default=None,
    show_envvar=True,
    envvar="JOINLY_LANGUAGE",
)
@click.option(
    "--vad",
    type=str,
    help='Voice Activity Detection service to use. Options are: "silero", "webrtc".',
    default=None,
    show_envvar=True,
    envvar="JOINLY_VAD",
)
@click.option(
    "--stt",
    type=str,
    help='Speech-to-Text service to use. Options are: "whisper" (local), "deepgram".',
    default=None,
    show_envvar=True,
    envvar="JOINLY_STT",
)
@click.option(
    "--tts",
    type=str,
    help='Text-to-Speech service to use. Options are: "kokoro" (local), '
    '"elevenlabs", "deepgram".',
    default=None,
    show_envvar=True,
    envvar="JOINLY_TTS",
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
@click.argument(
    "meeting-url",
    type=str,
    required=True,
)
def cli(  # noqa: PLR0913
    *,
    joinly_url: str,
    name: str,
    llm_provider: str,
    llm_model: str,
    prompt: str | None,
    prompt_file: str | None,
    prompt_style: str,
    name_trigger: bool,
    mcp_config: str | None,
    meeting_url: str,
    verbose: int,
    quiet: bool,
    **settings: Any,  # noqa: ANN401
) -> None:
    """Run the joinly client."""
    from rich.logging import RichHandler

    log_level = logging.WARNING
    if quiet:
        log_level = logging.ERROR
    elif verbose == 1:
        log_level = logging.INFO
    elif verbose == 2:  # noqa: PLR2004
        log_level = logging.DEBUG

    logging.basicConfig(
        level=logging.WARNING if not quiet else logging.ERROR,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )
    logging.getLogger("joinly_client").setLevel(log_level)

    if prompt_file and not prompt:
        try:
            with Path(prompt_file).open("r") as f:
                prompt = f.read().strip()
        except Exception:
            logger.exception("Failed to load prompt file")
            prompt = None

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
                meeting_url=meeting_url,
                llm_provider=llm_provider,
                llm_model=llm_model,
                prompt=prompt,
                prompt_style=prompt_style,
                name=name,
                name_trigger=name_trigger,
                mcp_config=mcp_config_dict,
                settings={k: v for k, v in settings.items() if v is not None},
            )
        )
    except KeyboardInterrupt:
        logger.info("Exiting due to keyboard interrupt.")


async def run(  # noqa: PLR0913
    joinly_url: str | FastMCP,
    meeting_url: str,
    llm_provider: str,
    llm_model: str,
    *,
    prompt: str | None = None,
    prompt_style: str | None = None,
    name: str | None = None,
    name_trigger: bool = False,
    mcp_config: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> None:
    """Run the joinly client.

    Args:
        joinly_url (str | FastMCP): The URL of the joinly server or a FastMCP instance.
        meeting_url (str): The URL of the meeting to join.
        llm_provider (str): The provider of the LLM model to use.
        llm_model (str): The name of the LLM model to use.
        prompt (str | None): System prompt to use for the model.
        prompt_style (str | None): Default prompt to use if no custom one is provided.
        name (str | None): The name of the participant.
        name_trigger (bool): Whether to trigger the agent only when the name is
            mentioned.
        mcp_config (dict[str, Any] | None): Configuration for additional MCP servers.
        settings (dict[str, Any] | None): Additional settings for the client.
    """
    client = JoinlyClient(
        joinly_url,
        name=name,
        name_trigger=name_trigger,
        settings=settings,
    )

    if mcp_config and "mcpServers" not in mcp_config:
        logger.warning(
            "MCP configuration does not contain 'mcpServers'. "
            "Using the main joinly client only."
        )
        mcp_config = None
    elif mcp_config and "joinly" in mcp_config["mcpServers"]:
        mcp_config["_joinly"] = mcp_config.pop("joinly")

    additional_clients = (
        {
            name: Client({"mcpServers": {name: config}})
            for name, config in mcp_config["mcpServers"].items()
        }
        if mcp_config
        else {}
    )

    async def log_segments(segments: list[TranscriptSegment]) -> None:
        """Log segments received from the client."""
        for segment in segments:
            logger.info('%s: "%s"', segment.speaker or "Participant", segment.text)

    client.add_segment_callback(log_segments)
    llm = get_llm(llm_provider, llm_model)

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(client)
        for client_name, additional_client in additional_clients.items():
            logger.info("Connecting to %s", client_name)
            await stack.enter_async_context(additional_client)
            logger.debug("Connected to %s", client_name)

        joinly_config = McpClientConfig(client=client.client, exclude=["join_meeting"])
        tools, tool_executor = await load_tools(
            joinly_config
            if not additional_clients
            else {
                "joinly": joinly_config,
                **{
                    name: McpClientConfig(client)
                    for name, client in additional_clients.items()
                },
            }
        )
        agent = ConversationalToolAgent(
            llm,
            tools,
            tool_executor,
            prompt=get_prompt(
                instructions=prompt,
                prompt_style=prompt_style,
                name=client.name,
            ),
        )
        client.add_utterance_callback(agent.on_utterance)
        async with agent:
            await client.join_meeting(meeting_url)
            try:
                await asyncio.Event().wait()
            finally:
                usage = agent.usage.merge(await client.get_usage())
                if usage.root:
                    logger.info("Usage:\n%s", usage)


if __name__ == "__main__":
    cli()
