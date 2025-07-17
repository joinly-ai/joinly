import os
from typing import Any

from fastmcp import Client
from pydantic_ai.models import Model, infer_model
from pydantic_ai.tools import ToolDefinition

from joinly_client.agent import ToolExecutor


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
                f"{os.getenv('OLLAMA_PORT', '11434')}"
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


async def load_tools(
    clients: Client | dict[str, Client],
) -> tuple[list[ToolDefinition], ToolExecutor]:
    """Load tools from the client.

    Args:
        clients (Client | dict[str, Client]): The client instance(s) to load tools from.

    Returns:
        tuple[list[ToolDefinition], ToolExecutor]: A list of tool definitions and a
            corresponding tool executor.
    """
    if isinstance(clients, Client):
        clients = {"default": clients}

    tools = []
    for prefix, client in clients.items():
        tools.extend(
            ToolDefinition(
                name=f"{prefix}_{tool.name}",
                description=tool.description,
                parameters_json_schema=tool.inputSchema,
            )
            for tool in await client.list_tools()
        )

    async def _tool_executor(tool_name: str, args: dict[str, Any]) -> Any:  # noqa: ANN401
        """Execute a tool with the given name and arguments."""
        prefix, tool_name = tool_name.split("_", 1)
        client = clients.get(prefix)
        if not client:
            msg = f"MCP '{prefix}' not found"
            raise ValueError(msg)
        result = await client.call_tool_mcp(tool_name, args)
        if result.structuredContent:
            return result.structuredContent
        texts = [p.text for p in result.content if p.type == "text"]
        return texts[0] if len(texts) == 1 else texts

    return tools, _tool_executor
