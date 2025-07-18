import asyncio
import os
from typing import Any

from fastmcp import Client
from mcp.types import (
    CancelledNotification,
    CancelledNotificationParams,
    ClientNotification,
)
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
    exclude: list[str] | None = None,
) -> tuple[list[ToolDefinition], ToolExecutor]:
    """Load tools from the client.

    Args:
        clients (Client | dict[str, Client]): The client instance(s) to load tools from.
        exclude (list[str] | None): List of tool names to exclude. Defaults to None.
            If clients is provided as a dictionary, the keys should be used as prefixes
            for the tool names.

    Returns:
        tuple[list[ToolDefinition], ToolExecutor]: A list of tool definitions and a
            corresponding tool executor.
    """
    if not exclude:
        exclude = []
    if isinstance(clients, Client):
        clients = {"default": clients}
        exclude = [f"default_{name}" for name in exclude]

    tools = []
    for prefix, client in clients.items():
        tools.extend(
            ToolDefinition(
                name=f"{prefix}_{tool.name}",
                description=tool.description,
                parameters_json_schema=tool.inputSchema,
            )
            for tool in await client.list_tools()
            if f"{prefix}_{tool.name}" not in exclude
        )

    async def _tool_executor(tool_name: str, args: dict[str, Any]) -> Any:  # noqa: ANN401
        """Execute a tool with the given name and arguments."""
        prefix, tool_name = tool_name.split("_", 1)
        client = clients.get(prefix)
        if not client:
            msg = f"MCP '{prefix}' not found"
            raise ValueError(msg)

        request_id = client.session._request_id  # noqa: SLF001
        try:
            result = await client.call_tool_mcp(tool_name, args)
        except asyncio.CancelledError:
            await client.session.send_notification(
                ClientNotification(
                    CancelledNotification(
                        method="notifications/cancelled",
                        params=CancelledNotificationParams(requestId=request_id),
                    )
                ),
                related_request_id=request_id,
            )
            return "Request cancelled"

        if result.structuredContent:
            return result.structuredContent
        texts = [p.text for p in result.content if p.type == "text"]
        return texts[0] if len(texts) == 1 else texts

    return tools, _tool_executor
