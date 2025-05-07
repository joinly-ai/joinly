import logging
import os
from contextlib import AsyncExitStack
from typing import Self

from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class BrowserAgent:
    """A class to manage the browser operations."""

    def __init__(
        self, *, env: dict[str, str] | None = None, mcp_port: int | None = None
    ) -> None:
        """Initialize the BrowserAgent class.

        Args:
            env (dict[str, str]): Environment variables for the Browser MCP.
            mcp_port (int | None): The port for the MCP server, 0 for auto-assign,
                None for stdio only (default: None).
        """
        self._env: dict[str, str] = env if env is not None else os.environ.copy()
        self._mcp_port: int | None = mcp_port

        self._agent = None
        self._exit_stack: AsyncExitStack = AsyncExitStack()

    async def __aenter__(self) -> Self:
        """Start the MCP client and initialize the agent."""
        cdp_endpoint = self._env.get("CDP_ENDPOINT", None)
        args = []
        if cdp_endpoint is not None:
            args += ["--cdp-endpoint", cdp_endpoint]
        if self._mcp_port is not None:
            args += ["--port", str(self._mcp_port)]
        logger.info("Starting MCP client with args: %s", args)

        read, write = await self._exit_stack.enter_async_context(
            stdio_client(
                StdioServerParameters(
                    command="npx",
                    args=["@playwright/mcp", *args],
                    env=self._env,
                )
            )
        )

        session = await self._exit_stack.enter_async_context(ClientSession(read, write))

        await session.initialize()

        llm = AzureChatOpenAI(
            azure_deployment="gpt-4o-mini",
            api_version="2024-12-01-preview",
        )

        tools = await load_mcp_tools(session)
        self._agent = create_react_agent(llm, tools)

        logger.info("Browser agent initialized successfully.")

        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the MCP client."""
        await self._exit_stack.aclose()
        self._agent = None

    async def run(self, task: str) -> None:
        """Run the agent with the given task.

        Args:
            task (str): The task to run the agent with.
        """
        if self._agent is None:
            msg = "Agent is not initialized"
            raise RuntimeError(msg)

        logger.info("Running browser agent with task: %s", task)

        prompt = f"Fulfill the following task requiring browser navigation. First, make sure you are on the right tab using the tab list tool. Then, get the elements on the page using the snapshot tool. Task: {task}"  # noqa: E501

        async for chunk in self._agent.astream(
            {"messages": prompt}, stream_mode="updates"
        ):
            logger.info(chunk)

        logger.info("Browser agent run completed for task: %s.", task)
