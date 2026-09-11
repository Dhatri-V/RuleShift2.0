from uuid import uuid4
from core.attendance_source import attendance_provisions, ordinary_attendance_question

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ai.llm import get_embeddings, get_llm


CHROMA_DIRECTORY = "./chroma_db"
COLLECTION_NAME = "policy_documents"

INSUFFICIENT_EVIDENCE_ANSWER = (
    "I could not find enough evidence in this policy version to answer that question."
)


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
        add_start_index=True,
    )

    return text_splitter.split_documents(page_documents)


def store_policy_pages(policy_name, version, pages, *, chunks=None):
    # Uploads supply persisted, ownership-enriched clauses. Legacy callers retain
    # the existing standalone page-indexing helper. Retrieval is unchanged.
    if chunks is None:
        chunks = create_policy_chunks(policy_name, version, pages)

    if not chunks:
        return 0

    vector_store = get_vector_store()
    chunk_ids = [
        f"clause:{chunk.metadata['source_sha256']}:{chunk.metadata['version_id']}:{chunk.metadata['clause_id']}"
        if "clause_id" in chunk.metadata else str(uuid4())
        for chunk in chunks
    ]
    vector_store.add_documents(documents=chunks, ids=chunk_ids)

    return len(chunks)


def delete_policy_chunks(policy_name, version):
    """Remove every chunk belonging to one policy version from Chroma.

    Used when a DRAFT policy is deleted so no orphaned RAG data remains.
    """
    vector_store = get_vector_store()
    vector_store.delete(where=version_filter(policy_name, version))


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

    # Defense in depth: retrieval already filters by exact policy name and
    # version, but no chunk from another policy or version may ever reach the
    # answer or the evidence list.
    documents = [
        document
        for document in documents
        if document.metadata.get("policy_name") == policy_name
        and document.metadata.get("version") == version
    ]

    if not documents:
        return {
            "answer": INSUFFICIENT_EVIDENCE_ANSWER,
            "evidence": [],
        }

    context_parts = []
    evidence = []

    for document in documents:
        page_number = document.metadata["page_number"]
        context_parts.append(
            f"Policy: {document.metadata['policy_name']}\n"
            f"Version: {document.metadata['version']}\n"
            f"Page {page_number}:\n{document.page_content}"
        )
        evidence.append(
            {
                "policy_name": document.metadata["policy_name"],
                "version": document.metadata["version"],
                "page_number": page_number,
                "text": document.page_content,
            }
        )

    context = "\n\n".join(context_parts)

    prompt = f"""
You are answering a question about one specific policy version.
Answer using ONLY the retrieved context below.
Do NOT use any general knowledge or outside information.
Never invent facts, policy names, versions, or page numbers.

If the retrieved context does not contain enough information to answer the question,
respond with exactly:
"{INSUFFICIENT_EVIDENCE_ANSWER}"

Retrieved context:
{context}

Question:
{question}
"""

    response = get_llm().invoke(prompt)

    answer = response.content
    # Recover only an explicit ordinary-rule answer from selected-version evidence.
    # Never generalise this to eligibility, exceptions, or multiple thresholds.
    if INSUFFICIENT_EVIDENCE_ANSWER.lower() in answer.lower() and ordinary_attendance_question(question):
        facts = [(fact, item) for item in evidence for fact in attendance_provisions(item['text'])]
        if len({fact['value'] for fact, _ in facts}) == 1:
            fact, item = facts[0]
            answer = f"{fact['quote']} (Page {item['page_number']}.) Refer to the cited passage for scope and exceptions."
            evidence = [item]

    return {
        "answer": answer,
        "evidence": evidence,
    }
