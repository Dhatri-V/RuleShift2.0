from uuid import uuid4

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ai.llm import get_embeddings, get_llm


CHROMA_DIRECTORY = "./chroma_db"
COLLECTION_NAME = "policy_documents"


def get_vector_store():
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=CHROMA_DIRECTORY,
    )


def create_policy_chunks(policy_name, version, pages):
    page_documents = []

    for page in pages:
        if page["text"]:
            page_documents.append(
                Document(
                    page_content=page["text"],
                    metadata={
                        "policy_name": policy_name,
                        "version": version,
                        "page_number": page["page_number"],
                    },
                )
            )

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
    )

    return text_splitter.split_documents(page_documents)


def store_policy_pages(policy_name, version, pages):
    chunks = create_policy_chunks(policy_name, version, pages)

    if not chunks:
        return 0

    vector_store = get_vector_store()
    chunk_ids = [str(uuid4()) for chunk in chunks]
    vector_store.add_documents(documents=chunks, ids=chunk_ids)

    return len(chunks)


def version_filter(policy_name, version):
    return {
        "$and": [
            {"policy_name": {"$eq": policy_name}},
            {"version": {"$eq": version}},
        ]
    }


def retrieve_policy_chunks(policy_name, version, question):
    vector_store = get_vector_store()

    return vector_store.similarity_search(
        question,
        k=4,
        filter=version_filter(policy_name, version),
    )


def answer_policy_question(policy_name, version, question):
    documents = retrieve_policy_chunks(policy_name, version, question)

    if not documents:
        return {
            "answer": "No information was found for that policy version.",
            "sources": [],
        }

    context_parts = []
    sources = []

    for document in documents:
        page_number = document.metadata["page_number"]
        context_parts.append(f"Page {page_number}:\n{document.page_content}")
        sources.append(
            {
                "policy_name": document.metadata["policy_name"],
                "version": document.metadata["version"],
                "page_number": page_number,
            }
        )

    context = "\n\n".join(context_parts)

    prompt = f"""
Answer the question using only the policy context below.
If the context does not contain the answer, say that the information was not found.

Policy context:
{context}

Question:
{question}
"""

    response = get_llm().invoke(prompt)

    return {
        "answer": response.content,
        "sources": sources,
    }
