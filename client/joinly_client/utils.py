from llama_index.core.llms import LLM


def get_llm(llm_provider: str, llm_model: str) -> LLM:
    """Retrieve the LLM based on the provider and model."""
    if llm_provider == "openai":
        from llama_index.llms.openai import OpenAI

        return OpenAI(model=llm_model)

    if llm_provider == "anthropic":
        from llama_index.llms.anthropic import Anthropic

        return Anthropic(model=llm_model)

    if llm_provider == "azure_openai":
        from llama_index.llms.azure_openai import AzureOpenAI

        return AzureOpenAI(model=llm_model)

    if llm_provider == "ollama":
        from llama_index.llms.ollama import Ollama

        return Ollama(model=llm_model)

    msg = f"Unsupported LLM provider: {llm_provider}."
    raise ValueError(msg)
