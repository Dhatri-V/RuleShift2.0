"""Focused tests for DRAFT policy deletion.

Covers: authorized deletion, unauthenticated rejection, non-DRAFT
rejection, Chroma chunk cleanup, and 404 for unknown policies.
Ollama is mocked; SQLite runs in memory; Chroma runs against a
temporary directory with deterministic stub embeddings.
"""

import zlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai.rag import delete_policy_chunks, retrieve_policy_chunks, store_policy_pages
from backend.main import app, get_database
from core.auth import require_admin
from database.db import Base


@pytest.fixture()
def client():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    def override_database():
        database = testing_session()
        try:
            yield database
        finally:
            database.close()

    app.dependency_overrides[get_database] = override_database
    # These tests cover deletion rules, not authentication.
    app.dependency_overrides[require_admin] = lambda: {"sub": "admin", "role": "admin"}
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


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
def isolated_chroma(tmp_path):
    return Chroma(
        collection_name="policy_documents_delete_test",
        embedding_function=StubEmbeddings(),
        persist_directory=str(tmp_path),
    )


def create_draft(client, version="2026", name="Academic Attendance Policy"):
    response = client.post(
        "/policies",
        json={
            "name": name,
            "version": version,
            "attendance_requirement": 80,
        },
    )
    assert response.status_code == 200
    return response.json()


def create_verified(client, version="2026", name="Academic Attendance Policy"):
    policy = create_draft(client, version=version, name=name)
    response = client.post(f"/policies/{policy['id']}/verify")
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------------------
# Authorized deletion
# ---------------------------------------------------------------------------


def test_authorized_draft_deletion_succeeds(client):
    policy = create_draft(client, version="2026")

    response = client.delete(f"/policies/{policy['id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] is True
    assert data["id"] == policy["id"]

    remaining = client.get("/policies").json()
    assert all(item["id"] != policy["id"] for item in remaining)


def test_delete_nonexistent_policy_returns_not_found(client):
    response = client.delete("/policies/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Policy not found."


def test_delete_nonexistent_policy_has_no_side_effects(client):
    policy = create_draft(client, version="2026")

    response = client.delete("/policies/999999")

    assert response.status_code == 404
    # The unrelated existing policy is completely unaffected.
    remaining = client.get("/policies").json()
    assert any(item["id"] == policy["id"] for item in remaining)


def test_invalid_token_deletion_rejected(client):
    policy = create_draft(client, version="2026")

    app.dependency_overrides.pop(require_admin, None)
    try:
        response = client.delete(
            f"/policies/{policy['id']}",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
    finally:
        app.dependency_overrides[require_admin] = lambda: {"sub": "admin", "role": "admin"}

    assert response.status_code == 401
    remaining = client.get("/policies").json()
    assert any(item["id"] == policy["id"] for item in remaining)


def test_expired_token_deletion_rejected(client):
    from core.auth import JWT_ALGORITHM
    from core.config import get_jwt_secret

    policy = create_draft(client, version="2026")
    expired = jwt.encode(
        {
            "sub": "admin@ruleshift.test",
            "role": "admin",
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        },
        get_jwt_secret(),
        algorithm=JWT_ALGORITHM,
    )

    app.dependency_overrides.pop(require_admin, None)
    try:
        response = client.delete(
            f"/policies/{policy['id']}",
            headers={"Authorization": f"Bearer {expired}"},
        )
    finally:
        app.dependency_overrides[require_admin] = lambda: {"sub": "admin", "role": "admin"}

    assert response.status_code == 401
    remaining = client.get("/policies").json()
    assert any(item["id"] == policy["id"] for item in remaining)


# ---------------------------------------------------------------------------
# Unauthenticated deletion
# ---------------------------------------------------------------------------


def test_unauthenticated_deletion_rejected(client):
    policy = create_draft(client, version="2026")

    # Remove the auth bypass to simulate a caller without a token.
    app.dependency_overrides.pop(require_admin, None)
    try:
        response = client.delete(f"/policies/{policy['id']}")
    finally:
        app.dependency_overrides[require_admin] = lambda: {"sub": "admin", "role": "admin"}

    assert response.status_code == 401
    # The draft policy must still exist.
    remaining = client.get("/policies").json()
    assert any(item["id"] == policy["id"] for item in remaining)


# ---------------------------------------------------------------------------
# Non-DRAFT rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("setup", ["verified", "current", "superseded"])
def test_non_draft_policies_cannot_be_deleted(client, setup):
    if setup == "verified":
        policy = create_verified(client, version="2026")
    elif setup == "current":
        policy = create_verified(client, version="2026")
        client.post(f"/policies/{policy['id']}/mark-current")
    else:  # superseded
        old_policy = create_verified(client, version="2025")
        client.post(f"/policies/{old_policy['id']}/mark-current")
        new_policy = create_verified(client, version="2026")
        client.post(f"/policies/{new_policy['id']}/mark-current")
        policy = old_policy

    response = client.delete(f"/policies/{policy['id']}")

    assert response.status_code == 409
    assert "Only DRAFT policies can be deleted" in response.json()["detail"]

    # The policy must still exist with its original status.
    statuses = {p["id"]: p["status"] for p in client.get("/policies").json()}
    assert statuses[policy["id"]] != "DRAFT"


# ---------------------------------------------------------------------------
# Chroma cleanup
# ---------------------------------------------------------------------------


@patch("ai.rag.get_vector_store")
def test_deletion_removes_chroma_chunks(mock_get_vector_store, client, isolated_chroma):
    mock_get_vector_store.return_value = isolated_chroma
    pages = [
        {"page_number": 1, "text": "Students must maintain at least 85% attendance."},
        {"page_number": 2, "text": "Exceptions apply for medical leave."},
    ]
    store_policy_pages("Academic Attendance Policy", "2026", pages)
    store_policy_pages("Academic Attendance Policy", "2025", pages)

    draft = create_draft(client, version="2026")

    response = client.delete(f"/policies/{draft['id']}")

    assert response.status_code == 200

    # 2026 chunks are gone; 2025 chunks remain untouched.
    remaining_2026 = retrieve_policy_chunks(
        "Academic Attendance Policy", "2026", "What attendance is required?"
    )
    remaining_2025 = retrieve_policy_chunks(
        "Academic Attendance Policy", "2025", "What attendance is required?"
    )
    assert remaining_2026 == []
    assert remaining_2025


@patch("backend.main.delete_policy_chunks")
def test_deletion_calls_chroma_cleanup_with_policy_identity(
    mock_delete_chunks, client
):
    policy = create_draft(client, version="2026")

    response = client.delete(f"/policies/{policy['id']}")

    assert response.status_code == 200
    mock_delete_chunks.assert_called_once_with(
        "Academic Attendance Policy", "2026"
    )


@patch("backend.main.delete_policy_chunks")
def test_chroma_failure_aborts_deletion_and_keeps_policy(
    mock_delete_chunks, client
):
    mock_delete_chunks.side_effect = RuntimeError("Chroma unavailable")
    policy = create_draft(client, version="2026")

    response = client.delete(f"/policies/{policy['id']}")

    assert response.status_code == 503

    # SQLite is authoritative: the policy row must still exist.
    remaining = client.get("/policies").json()
    assert any(item["id"] == policy["id"] for item in remaining)


# ---------------------------------------------------------------------------
# Isolation: other versions and other policy names are never touched
# ---------------------------------------------------------------------------


@patch("ai.rag.get_vector_store")
def test_other_versions_remain_in_chroma_after_deletion(
    mock_get_vector_store, client, isolated_chroma
):
    mock_get_vector_store.return_value = isolated_chroma
    pages = [
        {"page_number": 1, "text": "Students must maintain at least 85% attendance."},
    ]
    store_policy_pages("Academic Attendance Policy", "2025", pages)
    store_policy_pages("Academic Attendance Policy", "2026", pages)

    draft_2026 = create_draft(client, version="2026")

    response = client.delete(f"/policies/{draft_2026['id']}")

    assert response.status_code == 200
    # Only the deleted version's chunks are gone.
    assert retrieve_policy_chunks(
        "Academic Attendance Policy", "2026", "What attendance is required?"
    ) == []
    assert retrieve_policy_chunks(
        "Academic Attendance Policy", "2025", "What attendance is required?"
    )


@patch("ai.rag.get_vector_store")
def test_other_policy_names_remain_in_chroma_after_deletion(
    mock_get_vector_store, client, isolated_chroma
):
    mock_get_vector_store.return_value = isolated_chroma
    pages = [
        {"page_number": 1, "text": "Library books are due within fourteen days."},
    ]
    store_policy_pages("Library Policy", "2026", pages)
    store_policy_pages("Academic Attendance Policy", "2026", pages)

    draft = create_draft(client, version="2026", name="Academic Attendance Policy")

    response = client.delete(f"/policies/{draft['id']}")

    assert response.status_code == 200
    assert retrieve_policy_chunks(
        "Academic Attendance Policy", "2026", "What attendance is required?"
    ) == []
    assert retrieve_policy_chunks(
        "Library Policy", "2026", "When are books due?"
    )


# ---------------------------------------------------------------------------
# Consistency, partial-deletion safety, and idempotence
# ---------------------------------------------------------------------------


@patch("ai.rag.get_vector_store")
def test_successful_deletion_keeps_sqlite_and_chroma_consistent(
    mock_get_vector_store, client, isolated_chroma
):
    mock_get_vector_store.return_value = isolated_chroma
    pages = [
        {"page_number": 1, "text": "Students must maintain at least 85% attendance."},
    ]
    store_policy_pages("Academic Attendance Policy", "2026", pages)

    draft = create_draft(client, version="2026")

    # Chunks exist before deletion.
    assert retrieve_policy_chunks(
        "Academic Attendance Policy", "2026", "What attendance is required?"
    )

    response = client.delete(f"/policies/{draft['id']}")

    assert response.status_code == 200
    # SQLite row gone...
    assert all(
        item["id"] != draft["id"] for item in client.get("/policies").json()
    )
    # ...and Chroma chunks gone for that exact policy_name + version.
    assert retrieve_policy_chunks(
        "Academic Attendance Policy", "2026", "What attendance is required?"
    ) == []


@patch("ai.rag.get_vector_store")
def test_rejected_deletion_preserves_sqlite_row_and_chroma_chunks(
    mock_get_vector_store, client, isolated_chroma
):
    mock_get_vector_store.return_value = isolated_chroma
    pages = [
        {"page_number": 1, "text": "Students must maintain at least 85% attendance."},
    ]
    store_policy_pages("Academic Attendance Policy", "2026", pages)

    policy = create_draft(client, version="2026")
    client.post(f"/policies/{policy['id']}/verify")  # now VERIFIED

    response = client.delete(f"/policies/{policy['id']}")

    assert response.status_code == 409
    # SQLite row remains...
    statuses = {p["id"]: p["status"] for p in client.get("/policies").json()}
    assert statuses[policy["id"]] == "VERIFIED"
    # ...and Chroma chunks remain (no partial deletion).
    assert retrieve_policy_chunks(
        "Academic Attendance Policy", "2026", "What attendance is required?"
    )


def test_duplicate_delete_returns_not_found_without_crashing(client):
    policy = create_draft(client, version="2026")

    first = client.delete(f"/policies/{policy['id']}")
    assert first.status_code == 200

    second = client.delete(f"/policies/{policy['id']}")

    assert second.status_code == 404
    # The API is still healthy after the repeated delete.
    assert client.get("/policies").status_code == 200
