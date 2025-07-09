import logging

from llama_index.core.llms import LLM

logger = logging.getLogger(__name__)


class ConversationalToolAgent:
    """A conversational agent implementation to interact with joinly."""

    def __init__(self, llm: LLM, prompt: str | None) -> None:
        """Initialize the conversational agent with a model name and provider.

        Args:
            llm (LLM): The LLM instance to use for the agent.
            prompt (str | None): An optional prompt to initialize the agent with.
        """
        self._llm = llm
        self._prompt = prompt
