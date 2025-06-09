import contextlib
import logging
from contextlib import AsyncExitStack

from fastmcp import Client
from fastmcp.client.transports import NpxStdioTransport
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import create_react_agent

from joinly.providers.browser.agents.base import BrowserAgent, BrowserAgentTaskResponse

logger = logging.getLogger(__name__)


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

        self._agent = None
        self._stack: AsyncExitStack = AsyncExitStack()

    async def connect(self, cdp_url: str) -> None:
        """Connect to the browser using the provided CDP URL.

        Args:
            cdp_url (str): The CDP URL to connect to.
        """
        if self._agent is not None:
            msg = "Agent is already connected."
            raise RuntimeError(msg)

        logger.info("Starting playwright-mcp with CDP URL: %s", cdp_url)
        args = ["--caps", "core,wait", "--cdp-endpoint", cdp_url]
        client = Client(NpxStdioTransport("@playwright/mcp", args=args))
        await self._stack.enter_async_context(client)

        prompt = (
            "You are a browser agent that can navigate web pages, "
            "take snapshots, and interact with web elements. "
            "You will use the tools provided to fulfill tasks."
        )

        llm = init_chat_model(
            self._model_name, model_provider=self._model_provider, temperature=0.0
        )
        tools = await load_mcp_tools(client.session)
        self._agent = create_react_agent(
            llm, tools, prompt=prompt, response_format=BrowserAgentTaskResponse
        )

        logger.info("Playwright-mcp agent initialized successfully.")

    async def close(self) -> None:
        """Exit the MCP client."""
        with contextlib.suppress(Exception):
            await self._stack.aclose()
        self._agent = None

    async def run(self, task: str) -> BrowserAgentTaskResponse:
        """Run the agent with the given task.

        Args:
            task (str): The task to run the agent with.

        Returns:
            BrowserAgentTaskResponse: A response indicating the success or failure of
                the task.
        """
        if self._agent is None:
            msg = "Agent is not initialized"
            raise RuntimeError(msg)

        prompt = f"Task: {task}"
        output = await self._agent.ainvoke({"messages": prompt})

        return output["structured_response"]
