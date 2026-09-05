import zlib
from unittest.mock import MagicMock, patch

import pytest
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from ai.rag import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    answer_policy_question,
    create_policy_chunks,
    retrieve_policy_chunks,
    store_policy_pages,
    version_filter,
)


def test_version_filter_requires_exact_policy_name_and_version():
    policy_filter = version_filter("Academic Attendance Policy", "2026")

    assert policy_filter == {
        "$and": [
            {"policy_name": {"$eq": "Academic Attendance Policy"}},
            {"version": {"$eq": "2026"}},
        ]
    }


def test_create_policy_chunks_include_required_metadata():
    pages = [
        {"page_number": 1, "text": "Students must maintain at least 85% attendance."},
        {"page_number": 2, "text": "Exceptions are granted for medical reasons."},
    ]

    chunks = create_policy_chunks("Academic Attendance Policy", "2026", pages)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.metadata["policy_name"] == "Academic Attendance Policy"
        assert chunk.metadata["version"] == "2026"
        assert chunk.metadata["page_number"] in (1, 2)


@patch("ai.rag.get_vector_store")
def test_retrieve_policy_chunks_filters_by_exact_version(mock_get_vector_store):
    mock_store = MagicMock()
    mock_store.similarity_search.return_value = []
    mock_get_vector_store.return_value = mock_store

    retrieve_policy_chunks("Academic Attendance Policy", "2026", "What is required?")

    mock_store.similarity_search.assert_called_once_with(
        "What is required?",
        k=4,
        filter={
            "$and": [
                {"policy_name": {"$eq": "Academic Attendance Policy"}},
                {"version": {"$eq": "2026"}},
            ]
        },
    )


@patch("ai.rag.get_llm")
@patch("ai.rag.retrieve_policy_chunks")
def test_answer_policy_question_returns_evidence_with_text(mock_retrieve, mock_get_llm):
    mock_retrieve.return_value = [
        MagicMock(
            metadata={
                "policy_name": "Academic Attendance Policy",
                "version": "2026",
                "page_number": 1,
            },
            page_content="Students must maintain at least 85% attendance.",
        )
    ]
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="Students must maintain 85% attendance.")
    mock_get_llm.return_value = mock_llm

    result = answer_policy_question(
        "Academic Attendance Policy", "2026", "What attendance is required?"
    )

    assert result["answer"] == "Students must maintain 85% attendance."
    assert len(result["evidence"]) == 1
    evidence = result["evidence"][0]
    assert evidence["policy_name"] == "Academic Attendance Policy"
    assert evidence["version"] == "2026"
    assert evidence["page_number"] == 1
    assert "85%" in evidence["text"]


@patch("ai.rag.retrieve_policy_chunks")
def test_answer_policy_question_returns_safe_answer_when_no_evidence(mock_retrieve):
    mock_retrieve.return_value = []

    result = answer_policy_question(
        "Academic Attendance Policy", "2026", "What is the grading scale?"
    )

    assert result["answer"] == (
        "I could not find enough evidence in this policy version to answer that question."
    )
    assert result["evidence"] == []


@patch("ai.rag.get_llm")
@patch("ai.rag.retrieve_policy_chunks")
def test_answer_policy_question_never_leaks_other_versions(mock_retrieve, mock_get_llm):
    mock_retrieve.return_value = [
        MagicMock(
            metadata={
                "policy_name": "Academic Attendance Policy",
                "version": "2026",
                "page_number": 1,
            },
            page_content="2026 policy text about 85% attendance.",
        )
    ]
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="Answer from 2026 only.")
    mock_get_llm.return_value = mock_llm

    result = answer_policy_question(
        "Academic Attendance Policy", "2026", "What is the requirement?"
    )

    for evidence in result["evidence"]:
        assert evidence["version"] == "2026"

    prompt = mock_llm.invoke.call_args[0][0]
    assert "2026" in prompt
    assert "2025" not in prompt


class StubEmbeddings(Embeddings):
    """Deterministic embeddings so Chroma tests never need Ollama."""

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, text):
        return self._embed(text)

    def _embed(self, text):
        vector = [0.0] * 64
        for word in text.lower().split():
            vector[zlib.crc32(word.encode("utf-8")) % 64] += 1.0
        return vector


@pytest.fixture()
def real_chroma_store(tmp_path):
    store = Chroma(
        collection_name="policy_documents_test",
        embedding_function=StubEmbeddings(),
        persist_directory=str(tmp_path),
    )
    return store


POLICY_PAGES_2025 = [
    {
        "page_number": 1,
        "text": "Students must maintain a minimum attendance of 75 percent in the 2025 academic year.",
    },
    {
        "page_number": 2,
        "text": "The 2025 policy allows one medical exemption per semester.",
    },
]

POLICY_PAGES_2026 = [
    {
        "page_number": 1,
        "text": "Students must maintain a minimum attendance of 85 percent in the 2026 academic year.",
    },
    {
        "page_number": 2,
        "text": "The 2026 policy allows two medical exemptions per semester.",
    },
]

LIBRARY_PAGES_2026 = [
    {
        "page_number": 1,
        "text": "Library books must be returned within fourteen days of borrowing.",
    },
]


@patch("ai.rag.get_vector_store")
def test_2026_question_retrieves_only_2026_evidence(
    mock_get_vector_store, real_chroma_store
):
    mock_get_vector_store.return_value = real_chroma_store
    store_policy_pages("Academic Attendance Policy", "2025", POLICY_PAGES_2025)
    store_policy_pages("Academic Attendance Policy", "2026", POLICY_PAGES_2026)

    chunks = retrieve_policy_chunks(
        "Academic Attendance Policy",
        "2026",
        "What attendance percentage is required?",
    )

    assert chunks
    for chunk in chunks:
        assert chunk.metadata["policy_name"] == "Academic Attendance Policy"
        assert chunk.metadata["version"] == "2026"
        assert isinstance(chunk.metadata["page_number"], int)
        assert "2025" not in chunk.page_content


@patch("ai.rag.get_vector_store")
def test_2025_question_retrieves_only_2025_evidence(
    mock_get_vector_store, real_chroma_store
):
    mock_get_vector_store.return_value = real_chroma_store
    store_policy_pages("Academic Attendance Policy", "2025", POLICY_PAGES_2025)
    store_policy_pages("Academic Attendance Policy", "2026", POLICY_PAGES_2026)

    chunks = retrieve_policy_chunks(
        "Academic Attendance Policy",
        "2025",
        "What attendance percentage is required?",
    )

    assert chunks
    for chunk in chunks:
        assert chunk.metadata["policy_name"] == "Academic Attendance Policy"
        assert chunk.metadata["version"] == "2025"
        assert isinstance(chunk.metadata["page_number"], int)
        assert "2026" not in chunk.page_content


@patch("ai.rag.get_vector_store")
def test_versions_never_leak_into_each_others_context(
    mock_get_vector_store, real_chroma_store
):
    mock_get_vector_store.return_value = real_chroma_store
    store_policy_pages("Academic Attendance Policy", "2025", POLICY_PAGES_2025)
    store_policy_pages("Academic Attendance Policy", "2026", POLICY_PAGES_2026)

    chunks_2026 = retrieve_policy_chunks(
        "Academic Attendance Policy", "2026", "How many exemptions are allowed?"
    )
    chunks_2025 = retrieve_policy_chunks(
        "Academic Attendance Policy", "2025", "How many exemptions are allowed?"
    )

    assert chunks_2026 and chunks_2025
    assert all("2025" not in chunk.page_content for chunk in chunks_2026)
    assert all("2026" not in chunk.page_content for chunk in chunks_2025)


@patch("ai.rag.get_vector_store")
def test_other_policy_name_is_never_retrieved(mock_get_vector_store, real_chroma_store):
    mock_get_vector_store.return_value = real_chroma_store
    store_policy_pages("Library Policy", "2026", LIBRARY_PAGES_2026)

    chunks = retrieve_policy_chunks(
        "Academic Attendance Policy", "2026", "What attendance is required?"
    )

    assert chunks == []


@patch("ai.rag.get_llm")
@patch("ai.rag.get_vector_store")
def test_answer_evidence_contains_policy_version_and_page(
    mock_get_vector_store, mock_get_llm, real_chroma_store
):
    mock_get_vector_store.return_value = real_chroma_store
    store_policy_pages("Academic Attendance Policy", "2025", POLICY_PAGES_2025)
    store_policy_pages("Academic Attendance Policy", "2026", POLICY_PAGES_2026)

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content="Students must maintain at least 85% attendance."
    )
    mock_get_llm.return_value = mock_llm

    result = answer_policy_question(
        "Academic Attendance Policy",
        "2026",
        "What attendance percentage is required?",
    )

    assert result["evidence"]
    for item in result["evidence"]:
        assert item["policy_name"] == "Academic Attendance Policy"
        assert item["version"] == "2026"
        assert isinstance(item["page_number"], int)
        assert item["text"]
        assert "2025" not in item["text"]

    prompt = mock_llm.invoke.call_args[0][0]
    assert "2025" not in prompt


@patch("ai.rag.get_llm")
@patch("ai.rag.get_vector_store")
def test_insufficient_evidence_does_not_invent_answer(
    mock_get_vector_store, mock_get_llm, real_chroma_store
):
    mock_get_vector_store.return_value = real_chroma_store
    store_policy_pages("Academic Attendance Policy", "2026", POLICY_PAGES_2026)

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=INSUFFICIENT_EVIDENCE_ANSWER)
    mock_get_llm.return_value = mock_llm

    result = answer_policy_question(
        "Academic Attendance Policy",
        "2026",
        "What is the cafeteria lunch schedule?",
    )

    assert result["answer"] == INSUFFICIENT_EVIDENCE_ANSWER

    prompt = mock_llm.invoke.call_args[0][0]
    assert "Do NOT use any general knowledge" in prompt
    assert INSUFFICIENT_EVIDENCE_ANSWER in prompt


@patch("ai.rag.get_llm")
@patch("ai.rag.get_vector_store")
def test_missing_version_returns_safe_answer_without_llm(
    mock_get_vector_store, mock_get_llm, real_chroma_store
):
    mock_get_vector_store.return_value = real_chroma_store
    store_policy_pages("Academic Attendance Policy", "2025", POLICY_PAGES_2025)

    result = answer_policy_question(
        "Academic Attendance Policy",
        "2026",
        "What attendance percentage is required?",
    )

    assert result["answer"] == INSUFFICIENT_EVIDENCE_ANSWER
    assert result["evidence"] == []
    mock_get_llm.assert_not_called()


@patch("ai.rag.get_llm")
@patch("ai.rag.retrieve_policy_chunks")
def test_foreign_version_chunks_are_dropped_before_answering(
    mock_retrieve, mock_get_llm
):
    mock_retrieve.return_value = [
        MagicMock(
            metadata={
                "policy_name": "Academic Attendance Policy",
                "version": "2025",
                "page_number": 1,
            },
            page_content="2025 policy text about 75% attendance.",
        ),
        MagicMock(
            metadata={
                "policy_name": "Academic Attendance Policy",
                "version": "2026",
                "page_number": 1,
            },
            page_content="2026 policy text about 85% attendance.",
        ),
    ]
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content="Students must maintain at least 85% attendance."
    )
    mock_get_llm.return_value = mock_llm

    result = answer_policy_question(
        "Academic Attendance Policy", "2026", "What attendance is required?"
    )

    assert [item["version"] for item in result["evidence"]] == ["2026"]

    prompt = mock_llm.invoke.call_args[0][0]
    assert "2025" not in prompt
