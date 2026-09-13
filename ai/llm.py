from langchain_litellm import ChatLiteLLM
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from core.config import (
    ConfigError,
    get_embedding_api_key,
    get_embedding_model,
    get_embedding_provider,
    get_litellm_api_key,
    get_litellm_model,
)


def get_llm():
    return ChatLiteLLM(
        model=get_litellm_model(),
        api_key=get_litellm_api_key(),
        temperature=0,
    )


def get_embeddings():
    provider = get_embedding_provider()
    if provider != "google":
        raise ConfigError(
            f"Unsupported embedding provider '{provider}'. Only 'google' is configured."
        )
    return GoogleGenerativeAIEmbeddings(
        model=f"models/{get_embedding_model()}",
        google_api_key=get_embedding_api_key(),
    )
