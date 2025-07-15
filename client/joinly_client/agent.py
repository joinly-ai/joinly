import logging

from pydantic_ai.models import Model

logger = logging.getLogger(__name__)


class ConversationalToolAgent:
    """A conversational agent implementation to interact with joinly."""

    def __init__(self, llm: Model, prompt: str | None) -> None:
        """Initialize the conversational agent with a model.

        Args:
            llm (Model): The language model to use for the agent.
            prompt (str | None): An optional prompt to initialize the agent with.
        """
        self._llm = llm
        self._prompt = prompt
