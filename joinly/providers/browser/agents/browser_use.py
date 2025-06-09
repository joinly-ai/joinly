import logging

from browser_use import Agent, BrowserSession, Controller
from langchain.chat_models import init_chat_model

from joinly.providers.browser.agents.base import BrowserAgent, BrowserAgentTaskResponse

logger = logging.getLogger(__name__)


class BrowserUseBrowserAgent(BrowserAgent):
    """A class to manage the browser operations using browser-use."""

    def __init__(
        self,
        *,
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
        self._model_name: str = model_name
        self._model_provider: str | None = model_provider

        self._browser_session: BrowserSession | None = None
        self._llm = init_chat_model(
            self._model_name, model_provider=self._model_provider, temperature=0.0
        )

    async def connect(self, cdp_url: str) -> None:
        """Connect to the browser using the provided CDP URL.

        Args:
            cdp_url (str): The CDP URL to connect to.
        """
        if self._browser_session is not None:
            msg = "Agent is already connected."
            raise RuntimeError(msg)

        self._browser_session = BrowserSession(cdp_url=cdp_url)

    async def close(self) -> None:
        """Exit the Browser-use client."""
        if self._browser_session is not None:
            await self._browser_session.stop()
        self._browser_session = None

    async def run(self, task: str) -> BrowserAgentTaskResponse:
        """Run the agent with the given task.

        Args:
            task (str): The task to run the agent with.

        Returns:
            BrowserAgentTaskResponse: A response indicating the success or failure of
                the task.
        """
        if self._browser_session is None:
            msg = "Agent is not initialized"
            raise RuntimeError(msg)

        agent = Agent(
            task=task,
            llm=self._llm,
            browser_session=self._browser_session,
            enable_memory=False,
            controller=Controller(output_model=BrowserAgentTaskResponse),
        )
        history = await agent.run()
        result = history.final_result()

        if result is None:
            return BrowserAgentTaskResponse(
                success=False, message="No result returned from agent."
            )

        return BrowserAgentTaskResponse.model_validate_json(result)
