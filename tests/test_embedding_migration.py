from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from langchain_core.embeddings import Embeddings

import ai.rag as rag
from scripts import rebuild_index
from services.index_service import require_healthy_index

REAL_GET_VECTOR_STORE = rag.get_vector_store


class DeterministicEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[float(len(text)), 1.0] for text in texts]

    def embed_query(self, text):
        return [float(len(text)), 1.0]


def test_collection_identity_changes_with_embedding_model(monkeypatch):
    monkeypatch.setenv("RULESHIFT_EMBEDDING_PROVIDER", "google")
    monkeypatch.setenv("RULESHIFT_EMBEDDING_MODEL", "gemini-embedding-001")
    first = rag.current_collection_name()

    monkeypatch.setenv("RULESHIFT_EMBEDDING_MODEL", "gemini-embedding-2")
    second = rag.current_collection_name()

    assert first.startswith("policy_documents_")
    assert second.startswith("policy_documents_")
    assert first != second
    assert first != rag.COLLECTION_NAME


def test_reset_recreates_an_empty_current_model_collection(tmp_path, monkeypatch):
    monkeypatch.setenv("RULESHIFT_EMBEDDING_PROVIDER", "google")
    monkeypatch.setenv("RULESHIFT_EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setattr(rag, "get_chroma_path", lambda: str(tmp_path / "chroma"))
    monkeypatch.setattr(rag, "get_embeddings", DeterministicEmbeddings)
    monkeypatch.setattr(rag, "get_vector_store", REAL_GET_VECTOR_STORE)
    store = rag.get_vector_store()
    store.add_texts(["old vector"], ids=["old"])

    clean_store = rag.reset_current_vector_store()

    assert clean_store.get()["ids"] == []
    assert clean_store._collection.name == rag.current_collection_name()


def test_health_check_rejects_ready_generation_from_an_old_model(monkeypatch):
    stale = SimpleNamespace(
        generation=1,
        status="READY",
        collection_name="policy_documents",
        embedding_model="nomic-embed-text",
        expected_chunk_count=1,
        observed_chunk_count=1,
    )
    version = SimpleNamespace(index_generations=[stale], clauses=[object()], id=7)
    monkeypatch.setenv("RULESHIFT_EMBEDDING_PROVIDER", "google")
    monkeypatch.setenv("RULESHIFT_EMBEDDING_MODEL", "gemini-embedding-001")

    with pytest.raises(HTTPException) as error:
        require_healthy_index(version)

    assert error.value.status_code == 409
    assert "stale or incompatible" in error.value.detail


def test_health_check_accepts_only_matching_model_and_collection(monkeypatch):
    monkeypatch.setenv("RULESHIFT_EMBEDDING_PROVIDER", "google")
    monkeypatch.setenv("RULESHIFT_EMBEDDING_MODEL", "gemini-embedding-001")
    collection = rag.current_collection_name()
    compatible = SimpleNamespace(
        generation=2,
        status="READY",
        collection_name=collection,
        embedding_model="google:gemini-embedding-001",
        expected_chunk_count=1,
        observed_chunk_count=1,
    )
    version = SimpleNamespace(index_generations=[compatible], clauses=[object()], id=8)
    monkeypatch.setattr("services.index_service.observed_version_chunks", lambda version_id: 1)

    assert require_healthy_index(version) is compatible


def test_rebuild_script_resets_collection_before_rebuilding_every_version():
    events = []
    versions = [
        SimpleNamespace(id=1, clauses=[object()]),
        SimpleNamespace(id=2, clauses=[object()]),
    ]

    class Query:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def all(self):
            return versions

    class Database:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def query(self, model):
            return Query()

        def commit(self):
            events.append("commit")

        def rollback(self):
            events.append("rollback")

    def rebuild(database, version, **kwargs):
        events.append(f"rebuild:{version.id}")
        return SimpleNamespace(generation=1, observed_chunk_count=1)

    with (
        patch.object(rebuild_index, "SessionLocal", return_value=Database()),
        patch.object(rebuild_index.rag, "current_collection_name", return_value="policy_documents_new"),
        patch.object(rebuild_index.rag, "reset_current_vector_store", side_effect=lambda: events.append("reset")),
        patch.object(rebuild_index, "rebuild_version_index", side_effect=rebuild),
    ):
        rebuild_index.main()

    assert events == ["reset", "rebuild:1", "commit", "rebuild:2", "commit"]
