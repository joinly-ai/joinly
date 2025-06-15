import contextlib
import logging
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

from fastmcp import Client
from fastmcp.client.transports import NpxStdioTransport
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import create_react_agent

from joinly.providers.browser.agents.base import (
    BrowserAgent,
    BrowserAgentTaskResponse,
    TOutputModel,
)

if TYPE_CHECKING:
    from langchain.tools import BaseTool
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)

PROMPT = (
    "You are a browser agent that can navigate web pages, "
    "take snapshots, and interact with web elements. "
    "You will use the tools provided to fulfill tasks."
)


class PlaywrightMcpBrowserAgent(BrowserAgent):
    """A class to manage the browser operations using playwright-mcp."""

    def __init__(
        self,
        *,
        model_name: str = "gpt-4o",
        model_provider: str | None = None,
    ) -> None:
        """Initialize the BrowserAgent class.

        Args:
            model_name (str): The name of the model to use (default: "gpt-4o").
            model_provider (str | None): The provider of the model, otherwise
                it is automatically determined (default: None).
        """
        self._model_name: str = model_name
        self._model_provider: str | None = model_provider

        self._llm: BaseChatModel | None = None
        self._tools: list[BaseTool] | None = None
        self._stack: AsyncExitStack = AsyncExitStack()

    async def connect(self, cdp_url: str) -> None:
        """Connect to the browser using the provided CDP URL.

        Args:
            cdp_url (str): The CDP URL to connect to.
        """
        if self._llm is not None:
            msg = "Agent is already connected."
            raise RuntimeError(msg)

        logger.info("Starting playwright-mcp with CDP URL: %s", cdp_url)
        args = ["--caps", "core,wait", "--cdp-endpoint", cdp_url]
        client = Client(NpxStdioTransport("@playwright/mcp", args=args))
        await self._stack.enter_async_context(client)

        self._llm = init_chat_model(
            self._model_name, model_provider=self._model_provider, temperature=0.0
        )
        self._tools = await load_mcp_tools(client.session)

        logger.info("Playwright-mcp agent initialized successfully.")

    async def close(self) -> None:
        """Exit the MCP client."""
        with contextlib.suppress(Exception):
            await self._stack.aclose()
        self._agent = None

    async def run(
        self, task: str, output_type: type[TOutputModel] | None = None
    ) -> BrowserAgentTaskResponse[TOutputModel]:
        """Run the agent with the given task.

        Args:
            task (str): The task to run the agent with.
            output_type (BaseModel | None): An optional output model to validate the
                task result against.

        Returns:
            BrowserAgentTaskResponse: A response indicating the success or failure of
                the task and potential output.
        """
        if self._llm is None or self._tools is None:
            msg = "Agent is not initialized"
            raise RuntimeError(msg)

        agent = create_react_agent(
            self._llm,
            self._tools,
            prompt=PROMPT,
            response_format=BrowserAgentTaskResponse[TOutputModel],
        )

        task_prompt = f"Task: {task}"
        output = await agent.ainvoke({"messages": task_prompt})
        response: BrowserAgentTaskResponse[TOutputModel] = output["structured_response"]

        if response.output is None and output_type is not None and response.success:
            response = BrowserAgentTaskResponse[TOutputModel](
                success=False,
                message="No output provided, but output type was expected.",
            )

        return response
