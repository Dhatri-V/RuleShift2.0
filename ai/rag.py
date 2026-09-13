from uuid import uuid4
from hashlib import sha256
import re
from core.attendance_source import (
    attendance_provisions,
    ordinary_attendance_question,
    stated_attendance_for_comparison,
)
from core.evaluator import check_attendance
from core.config import get_chroma_path, get_embedding_identity

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ai.llm import get_embeddings, get_llm


CHROMA_DIRECTORY = "./chroma_db"
COLLECTION_NAME = "policy_documents"

INSUFFICIENT_EVIDENCE_ANSWER = (
    "I could not find enough evidence in this policy version to answer that question."
)


def current_collection_name():
    identity_hash = sha256(get_embedding_identity().encode()).hexdigest()[:12]
    return f"{COLLECTION_NAME}_{identity_hash}"


def get_vector_store():
    return Chroma(
        collection_name=current_collection_name(),
        embedding_function=get_embeddings(),
        persist_directory=get_chroma_path(),
    )


def reset_current_vector_store():
    """Replace the configured model's collection with a clean collection."""
    get_vector_store().delete_collection()
    return get_vector_store()


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


def policy_chunk_ids(chunks):
    return [
        f"clause:{chunk.metadata['source_sha256']}:{chunk.metadata['version_id']}:{chunk.metadata['clause_id']}"
        if "clause_id" in chunk.metadata else str(uuid4())
        for chunk in chunks
    ]


def delete_chunk_ids(chunk_ids):
    if chunk_ids:
        get_vector_store().delete(ids=list(chunk_ids))


def store_policy_pages(policy_name, version, pages, *, chunks=None):
    # Uploads supply persisted, ownership-enriched clauses. Legacy callers retain
    # the existing standalone page-indexing helper. Retrieval is unchanged.
    if chunks is None:
        chunks = create_policy_chunks(policy_name, version, pages)

    if not chunks:
        return 0

    vector_store = get_vector_store()
    chunk_ids = policy_chunk_ids(chunks)
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


def _number(value):
    return str(int(value)) if float(value).is_integer() else str(value)


def grounded_attendance_answer(question, evidence):
    """Resolve only explicit ordinary-threshold questions from source evidence."""
    measured_attendance = stated_attendance_for_comparison(question)
    if measured_attendance is None and not ordinary_attendance_question(question):
        return None

    facts = [(fact, item) for item in evidence for fact in attendance_provisions(item["text"])]
    if len({fact["value"] for fact, _ in facts}) != 1:
        return None

    fact, item = facts[0]
    if measured_attendance is None:
        return (
            f"{fact['quote']} (Page {item['page_number']}.) "
            "Refer to the cited passage for scope and exceptions."
        )

    requirement = fact["value"]
    measured = _number(measured_attendance)
    threshold = _number(requirement)
    result = check_attendance(measured_attendance, requirement)
    if result == "FAIL":
        return (
            f"No. The minimum attendance requirement is {threshold}%, so {measured}% "
            "attendance does not meet the requirement."
        )
    if abs(measured_attendance - requirement) < 1e-9:
        return (
            f"Yes. The minimum attendance requirement is {threshold}%, so exactly "
            f"{measured}% attendance is compliant."
        )
    return (
        f"Yes. The minimum attendance requirement is {threshold}%, so {measured}% "
        "attendance meets the requirement."
    )


def _evidence_payload(document):
    metadata = document.metadata
    return {
        "policy_id": metadata.get("policy_id"),
        "version_id": metadata.get("version_id"),
        "policy_name": metadata["policy_name"],
        "version": metadata["version"],
        "clause_id": metadata.get("clause_id"),
        "page_number": metadata["page_number"],
        "source_sha256": metadata.get("source_sha256"),
        "start_offset": metadata.get("start_offset"),
        "end_offset": metadata.get("end_offset"),
        "text": document.page_content,
    }


def _unsupported_numeric_claim(answer, evidence, question):
    claimed = {float(value) for value in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:%|percent\b)", answer, re.I)}
    supported = {float(value) for item in evidence for value in re.findall(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:%|percent\b)", item["text"], re.I
    )}
    supported.update(float(value) for value in re.findall(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:%|percent\b)", question, re.I
    ))
    return bool(claimed - supported)


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
            "answer_state": "INSUFFICIENT_EVIDENCE",
            "citations": [],
            "evidence": [],
        }

    if ordinary_attendance_question(question) or stated_attendance_for_comparison(question) is not None:
        documents.sort(key=lambda item: (not bool(attendance_provisions(item.page_content)), item.metadata.get("page_number", 0)))

    context_parts = []
    evidence = []

    for document in documents:
        page_number = document.metadata["page_number"]
        context_parts.append(
            f"Policy: {document.metadata['policy_name']}\n"
            f"Version: {document.metadata['version']}\n"
            f"Page {page_number}:\n{document.page_content}"
        )
        evidence.append(_evidence_payload(document))

    facts = [fact for item in evidence for fact in attendance_provisions(item["text"])]
    if (ordinary_attendance_question(question) or stated_attendance_for_comparison(question) is not None) and len({fact["value"] for fact in facts}) > 1:
        return {
            "answer": "I found conflicting attendance requirements in this policy version. An administrator must resolve the source conflict before this can be answered.",
            "answer_state": "CONFLICTING_EVIDENCE",
            "citations": [],
            "evidence": evidence,
        }

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
    deterministic_answer = grounded_attendance_answer(question, evidence)
    if deterministic_answer is not None and (
        stated_attendance_for_comparison(question) is not None
        or INSUFFICIENT_EVIDENCE_ANSWER.lower() in answer.lower()
    ):
        answer = deterministic_answer

    if _unsupported_numeric_claim(answer, evidence, question):
        answer = INSUFFICIENT_EVIDENCE_ANSWER

    answered = INSUFFICIENT_EVIDENCE_ANSWER.lower() not in answer.lower()
    primary = next((item for item in evidence if attendance_provisions(item["text"])), evidence[0]) if answered else None
    citations = [] if primary is None else [{
        key: primary.get(key) for key in (
            "policy_id", "version_id", "policy_name", "version", "clause_id",
            "page_number", "source_sha256", "start_offset", "end_offset"
        )
    }]
    return {
        "answer": answer,
        "answer_state": "ANSWERED" if answered else "INSUFFICIENT_EVIDENCE",
        "citations": citations,
        "evidence": evidence,
    }
