import os

from pydantic_ai.models import Model, infer_model


def get_llm(llm_provider: str, model_name: str) -> Model:
    """Get the LLM model based on the provider and model name.

    Args:
        llm_provider (str): The provider of the LLM (e.g., 'openai', 'anthropic').
        model_name (str): The name of the model to use.

    Returns:
        Model: An instance of the LLM model.
    """
    if llm_provider == "ollama":
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider

        ollama_url = os.getenv("OLLAMA_URL")
        if not ollama_url:
            ollama_url = (
                f"http://{os.getenv('OLLAMA_HOST', 'localhost')}:"
                f"{os.getenv('OLLAMA_PORT', '11434')}"
            )
        return OpenAIModel(
            model_name,
            provider=OpenAIProvider(
                base_url=ollama_url,
            ),
        )

    if llm_provider == "azure_openai":
        llm_provider = "azure"

    return infer_model(f"{llm_provider}:{model_name}")
