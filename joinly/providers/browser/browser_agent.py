import logging
import os
from contextlib import AsyncExitStack
from typing import Self

from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import create_react_agent
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from playwright.async_api import Page

logger = logging.getLogger(__name__)


class BrowserAgent:
    """A class to manage the browser operations."""

    def __init__(
        self,
        *,
        env: dict[str, str] | None = None,
        mcp_port: int | None = None,
        model_name: str = "gpt-4o",
        model_provider: str | None = None,
    ) -> None:
        """Initialize the BrowserAgent class.

        Args:
            env (dict[str, str]): Environment variables for the Browser MCP.
            mcp_port (int | None): The port for the MCP server, 0 for auto-assign,
                None for stdio only (default: None).
            model_name (str): The name of the model to use (default: "gpt-4o").
            model_provider (str | None): The provider of the model, otherwise
                it is automatically determined (default: None).
        """
        self._env: dict[str, str] = env if env is not None else os.environ.copy()
        self._mcp_port: int | None = mcp_port
        self._model_name: str = model_name
        self._model_provider: str | None = model_provider

        self._agent = None
        self._stack: AsyncExitStack = AsyncExitStack()

    async def __aenter__(self) -> Self:
        """Start the MCP client and initialize the agent."""
        cdp_endpoint = self._env.get("CDP_ENDPOINT", None)
        args = ["--caps", "core,wait"]
        if cdp_endpoint is not None:
            args += ["--cdp-endpoint", cdp_endpoint]
        if self._mcp_port is not None:
            args += ["--port", str(self._mcp_port)]
        logger.info("Starting MCP client with args: %s", args)

        read, write = await self._stack.enter_async_context(
            stdio_client(
                StdioServerParameters(
                    command="npx",
                    args=["@playwright/mcp", *args],
                    env=self._env,
                )
            )
        )

        session = await self._stack.enter_async_context(ClientSession(read, write))

        await session.initialize()

        llm = init_chat_model(
            self._model_name, model_provider=self._model_provider, temperature=0.0
        )

        prompt = (
            "You are a browser agent that can navigate web pages, "
            "take snapshots, and interact with web elements. "
            "You will use the tools provided to fulfill tasks."
        )
        tools = await load_mcp_tools(session)
        self._agent = create_react_agent(llm, tools, prompt=prompt)

        logger.info("Browser agent initialized successfully.")

        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the MCP client."""
        await self._stack.aclose()
        self._agent = None

    async def run(self, page: Page, task: str) -> None:  # noqa: ARG002
        """Run the agent with the given task.

        Args:
            page (Page): The Playwright page instance.
            task (str): The task to run the agent with.

        TODO: feedback on success or failure of the task
        """
        if self._agent is None:
            msg = "Agent is not initialized"
            raise RuntimeError(msg)

        logger.info("Running browser agent with task: %s", task)

        prompt = f"Task: {task}"

        async for chunk in self._agent.astream(
            {"messages": prompt}, {"recursion_limit": 10}, stream_mode="updates"
        ):
            logger.info(chunk)

        logger.info("Browser agent run completed for task: %s", task)
