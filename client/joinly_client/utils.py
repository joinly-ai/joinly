import asyncio
import logging
import os
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Never

from mcp import ClientSession
from pydantic_ai.mcp import MCPServer
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.openai import OpenAIModel, OpenAIResponsesModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition

from joinly_client.prompts import (
    DEFAULT_PROMPT_TEMPLATE,
    DYADIC_INSTRUCTIONS,
    MPC_INSTRUCTIONS,
)
from joinly_client.types import McpClientConfig, ToolExecutor, Transcript

logger = logging.getLogger(__name__)


def get_llm(llm_provider: str, model_name: str) -> Model:
    """Get the LLM model based on the provider and model name.

    Args:
        llm_provider (str): The provider of the LLM (e.g., 'openai', 'anthropic').
        model_name (str): The name of the model to use.

    Returns:
        Model: An instance of the LLM model.
    """
    if llm_provider == "ollama":
        ollama_url = os.getenv("OLLAMA_URL")
        if not ollama_url:
            ollama_url = (
                f"http://{os.getenv('OLLAMA_HOST', 'localhost')}:"
                f"{os.getenv('OLLAMA_PORT', '11434')}/v1"
            )
        return OpenAIModel(
            model_name,
            provider=OpenAIProvider(
                base_url=ollama_url,
            ),
        )

    if llm_provider == "azure_openai":
        llm_provider = "azure"

    if llm_provider == "google":
        llm_provider = "google-gla"

    # seems to fail with provider="azure"
    if llm_provider == "openai" and model_name.startswith("gpt-5"):
        model = OpenAIResponsesModel(
            model_name,
            provider=llm_provider,  # type: ignore[arg-type]
            settings=ModelSettings(
                extra_body={
                    "reasoning": {
                        "effort": "minimal",
                    },
                    "text": {
                        "verbosity": "low",
                    },
                }
            ),
        )
    else:
        model = infer_model(f"{llm_provider}:{model_name}")

    if model_name.startswith("gpt-5"):
        model.profile = model.profile.update(
            OpenAIModelProfile(openai_supports_sampling_settings=False)
        )

    return model


def get_prompt(
    template: str | None = None,
    instructions: str | None = None,
    prompt_style: str | None = None,
    name: str = "joinly",
) -> str:
    """Get the prompt template for the agent.

    Args:
        template (str): The prompt template to use. Defaults to DEFAULT_PROMPT_TEMPLATE.
        instructions (str): Instructions for the agent.
        If None, uses instructions based on prompt_style.
        prompt_style (str): The type of default instructions to use. Defaults to "mpc".
        name (str): The name of the agent. Defaults to 'joinly'.

    Returns:
        str: The formatted prompt template.
    """
    template = template if template is not None else DEFAULT_PROMPT_TEMPLATE
    if instructions is None:
        instructions = (
            DYADIC_INSTRUCTIONS if prompt_style == "dyadic" else MPC_INSTRUCTIONS
        )
    today = datetime.now(tz=UTC).date().isoformat()
    return template.format(date=today, name=name, instructions=instructions)


class _Mapper(MCPServer):
    def __init__(self, client: ClientSession) -> None:
        self._client = client

    async def client_streams(self) -> Never:  # type: ignore[override]
        raise RuntimeError


def sanitize_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:  # noqa: C901
    """Sanitize a tool schema.

    This function removes unsupported JSON schema features and ensures the schema
    is compatible with OpenAI's requirements.

    Args:
        schema (dict[str, Any]): The original JSON schema.

    Returns:
        dict[str, Any]: The sanitized JSON schema.
    """
    unsupported = {
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "$schema",
        "$id",
        "$ref",
        "definitions",
        "$defs",
        "patternProperties",
    }

    def default_object() -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": True}

    def choose_type(t: Any) -> str:  # noqa: ANN401
        if isinstance(t, list):
            return t[0] if t and isinstance(t[0], str) else "object"
        return t if isinstance(t, str) else "object"

    def walk(node: Any) -> dict[str, Any]:  # noqa: ANN401
        if not isinstance(node, dict):
            return default_object()
        out = {k: v for k, v in node.items() if k not in unsupported}
        t = choose_type(out.get("type", "object"))

        if t == "object":
            props = out.get("properties")
            props = props if isinstance(props, dict) else {}
            out["properties"] = {k: walk(v) for k, v in props.items()}
            ap = out.get("additionalProperties", True)
            out["additionalProperties"] = ap if isinstance(ap, bool) else True
            req = out.get("required")
            if isinstance(req, list):
                req = [k for k in req if isinstance(k, str) and k in out["properties"]]
                if req:
                    out["required"] = req
                else:
                    out.pop("required", None)
            out["type"] = "object"
            return out

        if t == "array":
            items = out.get("items")
            if isinstance(items, list):
                out["items"] = walk(items[0]) if items else default_object()
            elif isinstance(items, dict):
                out["items"] = walk(items)
            else:
                out["items"] = default_object()
            out["type"] = "array"
            return out

        out["type"] = t
        return out

    return walk(schema)


async def load_tools(  # noqa: C901
    clients: McpClientConfig | dict[str, McpClientConfig],
    sanitize_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = (
        sanitize_tool_schema
    ),
) -> tuple[list[ToolDefinition], ToolExecutor]:
    """Load tools from the client.

    Args:
        clients: A dictionary of client configurations, where the key is the client name
            and the value is the client configuration.
        sanitize_fn: A function to sanitize the tool schema. Defaults to
            sanitize_tool_schema. No sanitization if None.

    Returns:
        tuple[list[ToolDefinition], ToolExecutor]: A list of tool definitions and a
            corresponding tool executor.
    """
    tools = []
    client_items = clients.items() if isinstance(clients, dict) else [(None, clients)]
    for prefix, config in client_items:
        for tool in await config.client.list_tools():
            if tool.name in config.exclude:
                continue
            if config.include and tool.name not in config.include:
                continue

            if sanitize_fn is None:
                schema = tool.inputSchema
            else:
                try:
                    schema = sanitize_fn(tool.inputSchema)
                except Exception:
                    logger.exception(
                        "Error sanitizing schema for tool %s of MCP %s, skipping",
                        tool.name,
                        prefix,
                    )
                    continue

            tools.append(
                ToolDefinition(
                    name=f"{prefix}_{tool.name}" if prefix is not None else tool.name,
                    description=tool.description,
                    parameters_json_schema=schema,
                )
            )

    async def _tool_executor(tool_name: str, args: dict[str, Any]) -> Any:  # noqa: ANN401
        """Execute a tool with the given name and arguments."""
        if isinstance(clients, McpClientConfig):
            client = clients.client
            post_callback = clients.post_callback
        else:
            prefix, tool_name = tool_name.split("_", 1)
            if prefix not in clients:
                msg = f"MCP '{prefix}' not found"
                raise ValueError(msg)
            client = clients[prefix].client
            post_callback = clients[prefix].post_callback

        result = await client.call_tool_mcp(tool_name, args)
        if post_callback:
            result = await post_callback(tool_name, args, result)

        mapper = _Mapper(client.session)
        mapped = [await mapper._map_tool_result_part(p) for p in result.content]  # noqa: SLF001

        if result.isError:
            return f"[error] {'\n'.join(str(part) for part in mapped)}"

        return mapped[0] if len(mapped) == 1 else mapped

    return tools, _tool_executor


def normalize(s: str) -> str:
    """Normalize a string.

    Args:
        s: The string to normalize.

    Returns:
        The normalized string.
    """
    normalized = unicodedata.normalize("NFKD", s.casefold().strip())
    chars = (c for c in normalized if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s]", "", "".join(chars))


def name_in_transcript(transcript: Transcript, name: str) -> bool:
    """Check if the name is mentioned in the transcript.

    Args:
        transcript: The transcript to check.
        name: The name to look for.

    Returns:
        True if the name is mentioned in the transcript, False otherwise.
    """
    pattern = rf"\b{re.escape(normalize(name))}\b"
    return bool(re.search(pattern, normalize(transcript.text)))


def is_async_context() -> bool:
    """Check if the current context is asynchronous.

    Returns:
        bool: True if the current context is asynchronous, False otherwise.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    else:
        return True
