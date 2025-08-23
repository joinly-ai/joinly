import asyncio
import os
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

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


async def load_tools(
    clients: McpClientConfig | dict[str, McpClientConfig],
) -> tuple[list[ToolDefinition], ToolExecutor]:
    """Load tools from the client.

    Args:
        clients: A dictionary of client configurations, where the key is the client name
            and the value is the client configuration.

    Returns:
        tuple[list[ToolDefinition], ToolExecutor]: A list of tool definitions and a
            corresponding tool executor.
    """
    tools = []
    client_items = clients.items() if isinstance(clients, dict) else [(None, clients)]
    for prefix, config in client_items:
        tools.extend(
            ToolDefinition(
                name=f"{prefix}_{tool.name}" if prefix is not None else tool.name,
                description=tool.description,
                parameters_json_schema=tool.inputSchema,
            )
            for tool in await config.client.list_tools()
            if tool.name not in config.exclude
            and (not config.include or tool.name in config.include)
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
        if result.structuredContent:
            return result.structuredContent
        texts = [p.text for p in result.content if p.type == "text"]
        return texts[0] if len(texts) == 1 else texts

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
