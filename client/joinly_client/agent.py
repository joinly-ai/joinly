import logging

from langchain.chat_models import init_chat_model

logger = logging.getLogger(__name__)


def log_chunk(chunk) -> None:  # noqa: ANN001
    """Log an update chunk from langgraph."""
    if "agent" in chunk:
        for m in chunk["agent"]["messages"]:
            for t in m.tool_calls or []:
                args_str = ", ".join(
                    f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
                    for k, v in t.get("args", {}).items()
                )
                logger.info("%s: %s", t["name"], args_str)
    if "tools" in chunk:
        for m in chunk["tools"]["messages"]:
            logger.info("%s: %s", m.name, m.content)


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
        self._llm = init_chat_model(model_name, model_provider=model_provider)
        self._prompt = prompt
