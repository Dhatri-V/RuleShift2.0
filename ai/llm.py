from langchain_ollama import ChatOllama, OllamaEmbeddings


LLM_MODEL = "llama3.2:3b"
EMBEDDING_MODEL = "nomic-embed-text"


def get_llm():
    return ChatOllama(model=LLM_MODEL, temperature=0, num_ctx=8192)


def get_embeddings():
    return OllamaEmbeddings(model=EMBEDDING_MODEL)
