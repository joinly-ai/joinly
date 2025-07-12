import logging

logger = logging.getLogger(__name__)


class ConversationalToolAgent:
    """A conversational agent implementation to interact with joinly."""

    def __init__(self, llm_provider: str, llm_model: str, prompt: str | None) -> None:
        """Initialize the conversational agent with a model name and provider.

        Args:
            llm_provider (str): The provider of the LLM model.
            llm_model (str): The name of the LLM model.
            prompt (str | None): An optional prompt to initialize the agent with.
        """
        self._llm_provider = llm_provider
        self._llm_model = llm_model
        self._prompt = prompt
