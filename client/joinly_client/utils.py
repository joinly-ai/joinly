import asyncio
import os
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from pydantic_ai.models import Model, infer_model
from pydantic_ai.tools import ToolDefinition

from joinly_client.types import McpClientConfig, ToolExecutor, Transcript

DEFAULT_PROMPT_TEMPLATE = (
    "Today is {date}. "
    "You are {name}, a professional and knowledgeable meeting assistant. "
    "Provide concise, valuable contributions in the meeting. "
    "You are only with one other participant in the meeting, therefore "
    "respond to all messages and questions. "
    "When you are greeted, respond politely in spoken language. "
    "Give information, answer questions, and fullfill tasks as needed. "
    "You receive real-time transcripts from the ongoing meeting. "
    "Respond interactively and use available tools to assist participants. "
    "Always finish your response with the 'finish' tool. "
    "Never directly use the 'finish' tool, always respond first and then use it. "
    "If interrupted mid-response, use 'finish'."
)


def get_llm(llm_provider: str, model_name: str) -> Model:
    """Get the LLM model based on the provider and model name.

    Args:
        llm_provider (str): The provider of the LLM (e.g., 'openai', 'anthropic').
        model_name (str): The name of the model to use.

    Returns:
        Model: An instance of the LLM model.
    """
    if llm_provider == "ollama":
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider

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

    return infer_model(f"{llm_provider}:{model_name}")


def get_prompt(template: str = DEFAULT_PROMPT_TEMPLATE, name: str = "joinly") -> str:
    """Get the prompt template for the agent.

    Args:
        template (str): The prompt template to use. Defaults to DEFAULT_PROMPT_TEMPLATE.
        name (str): The name of the agent. Defaults to 'joinly'.

    Returns:
        str: The formatted prompt template.
    """
    today = datetime.now(tz=UTC).strftime("%d.%m.%Y")
    return template.format(name=name, date=today)


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
        )

    async def _tool_executor(tool_name: str, args: dict[str, Any]) -> Any:  # noqa: ANN401
        """Execute a tool with the given name and arguments."""
        if isinstance(clients, McpClientConfig):
            client = clients.client
        else:
            prefix, tool_name = tool_name.split("_", 1)
            if prefix not in clients:
                msg = f"MCP '{prefix}' not found"
                raise ValueError(msg)
            client = clients[prefix].client

        result = await client.call_tool_mcp(tool_name, args)
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
