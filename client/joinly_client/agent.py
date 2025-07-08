import logging

logger = logging.getLogger(__name__)


class ConversationalAgent:
    """A conversational agent implementation to interact with joinly."""

    def __init__(
        self, model_name: str, model_provider: str | None, prompt: str | None
    ) -> None:
        """Initialize the conversational agent with a model name and provider.

        Args:
            model_name (str): The name of the model to use.
            model_provider (str | None): The provider of the model, if any.
            prompt (str | None): An optional prompt to initialize the agent with.
        """
        self._model_name = model_name
        self._model_provider = model_provider
        self._prompt = prompt
