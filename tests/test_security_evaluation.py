"""
Security and evaluation hardening layer for RuleShift.

This module proves three guarantees and nothing else:

1. RAG evaluation  - version isolation, policy-name isolation, evidence
                     schema, and the safe fallback answer.
2. Lifecycle security - the DRAFT / VERIFIED / CURRENT / SUPERSEDED rules
                        cannot be bypassed through any endpoint.
3. Deterministic evaluation dataset - 2025 -> 75%, 2026 -> 85% must always
                      compare as INCREASED by 10 and impact attendance 80 as
                      NEWLY_NON_COMPLIANT and 90 as STILL_COMPLIANT.

Ollama is mocked everywhere; Chroma runs for real against a temporary
directory with deterministic stub embeddings; SQLite runs in memory.
"""

import zlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai.rag import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    answer_policy_question,
    retrieve_policy_chunks,
    store_policy_pages,
)
from backend.main import app, get_database
from core.auth import require_admin
from core.impact import compare_attendance_requirements, compare_rules
from database.db import Base


# ---------------------------------------------------------------------------
# Deterministic evaluation dataset
# ---------------------------------------------------------------------------

EVAL_POLICY_NAME = "Academic Attendance Policy"
EVAL_OLD_VERSION = "2025"
EVAL_OLD_REQUIREMENT = 75.0
EVAL_NEW_VERSION = "2026"
EVAL_NEW_REQUIREMENT = 85.0

EVAL_IMPACT_CASES = [
    (80, "NEWLY_NON_COMPLIANT"),
    (90, "STILL_COMPLIANT"),
]

EVAL_PAGES = {
    EVAL_OLD_VERSION: [
        {
            "page_number": 1,
            "text": (
                "Students must maintain a minimum attendance of 75 percent "
                "in the 2025 academic year."
            ),
        },
    ],
    EVAL_NEW_VERSION: [
        {
            "page_number": 1,
            "text": (
                "Students must maintain a minimum attendance of 85 percent "
                "in the 2026 academic year."
            ),
        },
    ],
}


# ---------------------------------------------------------------------------
# Shared, isolated fixtures (in-memory SQLite, temporary Chroma, no Ollama)
# ---------------------------------------------------------------------------


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
    # These tests cover RAG/lifecycle/deterministic rules, not authentication.
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
    from langchain_chroma import Chroma

    return Chroma(
        collection_name="policy_documents_eval",
        embedding_function=StubEmbeddings(),
        persist_directory=str(tmp_path),
    )


def create_verified(
    client,
    version="2026",
    attendance_requirement=80,
    name=EVAL_POLICY_NAME,
):
    response = client.post(
        "/policies",
        json={
            "name": name,
            "version": version,
            "attendance_requirement": attendance_requirement,
        },
    )
    assert response.status_code == 200
    policy = response.json()

    response = client.post(f"/policies/{policy['id']}/verify")
    assert response.status_code == 200
    return response.json()


def ask(client, policy_name, version, question="What attendance is required?"):
    return client.post(
        "/ask",
        json={
            "policy_name": policy_name,
            "version": version,
            "question": question,
        },
    )


# ---------------------------------------------------------------------------
# 1. RAG evaluation tests
# ---------------------------------------------------------------------------


@patch("ai.rag.get_llm")
@patch("ai.rag.get_vector_store")
def test_rag_eval_2025_query_never_returns_2026_evidence(
    mock_get_vector_store, mock_get_llm, isolated_chroma
):
    mock_get_vector_store.return_value = isolated_chroma
    store_policy_pages(EVAL_POLICY_NAME, EVAL_OLD_VERSION, EVAL_PAGES["2025"])
    store_policy_pages(EVAL_POLICY_NAME, EVAL_NEW_VERSION, EVAL_PAGES["2026"])
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="75 percent.")
    mock_get_llm.return_value = mock_llm

    result = answer_policy_question(
        EVAL_POLICY_NAME, EVAL_OLD_VERSION, "What attendance is required?"
    )

    assert result["evidence"]
    for item in result["evidence"]:
        assert item["version"] == "2025"
        assert item["version"] != "2026"
        assert "85 percent" not in item["text"]

    prompt = mock_llm.invoke.call_args[0][0]
    assert "2026" not in prompt


@patch("ai.rag.get_llm")
@patch("ai.rag.get_vector_store")
def test_rag_eval_2026_query_never_returns_2025_evidence(
    mock_get_vector_store, mock_get_llm, isolated_chroma
):
    mock_get_vector_store.return_value = isolated_chroma
    store_policy_pages(EVAL_POLICY_NAME, EVAL_OLD_VERSION, EVAL_PAGES["2025"])
    store_policy_pages(EVAL_POLICY_NAME, EVAL_NEW_VERSION, EVAL_PAGES["2026"])
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="85 percent.")
    mock_get_llm.return_value = mock_llm

    result = answer_policy_question(
        EVAL_POLICY_NAME, EVAL_NEW_VERSION, "What attendance is required?"
    )

    assert result["evidence"]
    for item in result["evidence"]:
        assert item["version"] == "2026"
        assert item["version"] != "2025"
        assert "75 percent" not in item["text"]

    prompt = mock_llm.invoke.call_args[0][0]
    assert "2025" not in prompt


@patch("ai.rag.get_vector_store")
def test_rag_eval_other_policy_names_never_leak_into_retrieval(
    mock_get_vector_store, isolated_chroma
):
    mock_get_vector_store.return_value = isolated_chroma
    store_policy_pages(
        "Library Policy",
        EVAL_NEW_VERSION,
        [{"page_number": 1, "text": "Library books are due after fourteen days."}],
    )

    chunks = retrieve_policy_chunks(
        EVAL_POLICY_NAME, EVAL_NEW_VERSION, "What attendance is required?"
    )

    assert chunks == []


@patch("ai.rag.get_llm")
@patch("ai.rag.get_vector_store")
@pytest.mark.parametrize("version", [EVAL_OLD_VERSION, EVAL_NEW_VERSION])
def test_rag_eval_every_evidence_item_has_required_fields(
    mock_get_vector_store, mock_get_llm, isolated_chroma, version
):
    mock_get_vector_store.return_value = isolated_chroma
    store_policy_pages(EVAL_POLICY_NAME, EVAL_OLD_VERSION, EVAL_PAGES["2025"])
    store_policy_pages(EVAL_POLICY_NAME, EVAL_NEW_VERSION, EVAL_PAGES["2026"])
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="Answer from context.")
    mock_get_llm.return_value = mock_llm

    result = answer_policy_question(
        EVAL_POLICY_NAME, version, "What attendance is required?"
    )

    assert result["evidence"]
    for item in result["evidence"]:
        assert set(item) == {"policy_name", "version", "page_number", "text"}
        assert item["policy_name"] == EVAL_POLICY_NAME
        assert item["version"] == version
        assert isinstance(item["page_number"], int)
        assert item["text"].strip()


@patch("ai.rag.get_llm")
@patch("ai.rag.get_vector_store")
def test_rag_eval_insufficient_evidence_returns_safe_fallback(
    mock_get_vector_store, mock_get_llm, isolated_chroma
):
    mock_get_vector_store.return_value = isolated_chroma
    store_policy_pages(EVAL_POLICY_NAME, EVAL_NEW_VERSION, EVAL_PAGES["2026"])
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=INSUFFICIENT_EVIDENCE_ANSWER)
    mock_get_llm.return_value = mock_llm

    result = answer_policy_question(
        EVAL_POLICY_NAME, EVAL_NEW_VERSION, "What is the cafeteria lunch menu?"
    )

    assert result["answer"] == INSUFFICIENT_EVIDENCE_ANSWER


def test_rag_eval_draft_policy_cannot_be_queried(client):
    response = client.post(
        "/policies",
        json={
            "name": EVAL_POLICY_NAME,
            "version": EVAL_NEW_VERSION,
            "attendance_requirement": 85,
        },
    )
    assert response.status_code == 200

    response = ask(client, EVAL_POLICY_NAME, EVAL_NEW_VERSION)

    assert response.status_code == 409
    assert "DRAFT" in response.json()["detail"]


def test_rag_eval_nonexistent_version_cannot_be_queried(client):
    create_verified(client, version=EVAL_OLD_VERSION, attendance_requirement=75)

    response = ask(client, EVAL_POLICY_NAME, "2019")

    assert response.status_code == 404
    assert "2019" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 2. Lifecycle security tests
# ---------------------------------------------------------------------------


def test_lifecycle_draft_cannot_become_current(client):
    response = client.post(
        "/policies",
        json={
            "name": EVAL_POLICY_NAME,
            "version": EVAL_NEW_VERSION,
            "attendance_requirement": 85,
        },
    )
    policy = response.json()
    assert policy["status"] == "DRAFT"

    response = client.post(f"/policies/{policy['id']}/mark-current")

    assert response.status_code == 409
    assert "Only VERIFIED" in response.json()["detail"]


def test_lifecycle_only_verified_can_become_current(client):
    old_policy = create_verified(client, version=EVAL_OLD_VERSION, attendance_requirement=75)
    client.post(f"/policies/{old_policy['id']}/mark-current")
    new_policy = create_verified(client, version=EVAL_NEW_VERSION, attendance_requirement=85)
    client.post(f"/policies/{new_policy['id']}/mark-current")

    # old_policy is now SUPERSEDED; it must not become CURRENT again.
    response = client.post(f"/policies/{old_policy['id']}/mark-current")

    assert response.status_code == 409
    assert "Only VERIFIED" in response.json()["detail"]


@pytest.mark.parametrize("status", ["VERIFIED", "CURRENT"])
def test_lifecycle_status_endpoint_cannot_bypass_lifecycle(client, status):
    policy = create_verified(client, version=EVAL_NEW_VERSION, attendance_requirement=85)

    response = client.patch(
        f"/policies/{policy['id']}/status",
        json={"status": status},
    )

    # The generic status endpoint must refuse to hand out VERIFIED/CURRENT
    # directly; those transitions only happen through their own endpoints.
    assert response.status_code == 400
    assert "endpoint" in response.json()["detail"]


def test_lifecycle_new_current_supersedes_previous_current(client):
    previous = create_verified(client, version=EVAL_OLD_VERSION, attendance_requirement=75)
    client.post(f"/policies/{previous['id']}/mark-current")
    latest = create_verified(client, version=EVAL_NEW_VERSION, attendance_requirement=85)

    response = client.post(f"/policies/{latest['id']}/mark-current")

    assert response.status_code == 200
    assert response.json()["superseded_id"] == previous["id"]
    statuses = {p["id"]: p["status"] for p in client.get("/policies").json()}
    assert statuses[latest["id"]] == "CURRENT"
    assert statuses[previous["id"]] == "SUPERSEDED"


def test_lifecycle_cannot_edit_rule_after_verification(client):
    policy = create_verified(client, version=EVAL_NEW_VERSION, attendance_requirement=85)

    response = client.patch(
        f"/policies/{policy['id']}/rule",
        json={"attendance_requirement": 60},
    )

    assert response.status_code == 409
    assert "Only DRAFT" in response.json()["detail"]


def test_lifecycle_cannot_reverify_verified_policy(client):
    policy = create_verified(client, version=EVAL_NEW_VERSION, attendance_requirement=85)

    response = client.post(f"/policies/{policy['id']}/verify")

    assert response.status_code == 409
    assert "Only DRAFT" in response.json()["detail"]


def test_lifecycle_cannot_compare_using_draft_policy(client):
    verified = create_verified(client, version=EVAL_OLD_VERSION, attendance_requirement=75)
    draft = client.post(
        "/policies",
        json={
            "name": EVAL_POLICY_NAME,
            "version": EVAL_NEW_VERSION,
            "attendance_requirement": 85,
        },
    ).json()

    response = client.post(
        "/compare-versions",
        json={"old_policy_id": verified["id"], "new_policy_id": draft["id"]},
    )

    assert response.status_code == 409
    assert "DRAFT" in response.json()["detail"]


def test_lifecycle_cannot_calculate_student_impact_using_draft_policy(client):
    verified = create_verified(client, version=EVAL_OLD_VERSION, attendance_requirement=75)
    draft = client.post(
        "/policies",
        json={
            "name": EVAL_POLICY_NAME,
            "version": EVAL_NEW_VERSION,
            "attendance_requirement": 85,
        },
    ).json()

    response = client.post(
        "/student-impact",
        json={
            "old_policy_id": verified["id"],
            "new_policy_id": draft["id"],
            "attendance": 80,
        },
    )

    assert response.status_code == 409
    assert "DRAFT" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 3. Deterministic evaluation dataset
# ---------------------------------------------------------------------------


def test_eval_dataset_comparison_is_increased_by_ten():
    result = compare_attendance_requirements(EVAL_OLD_REQUIREMENT, EVAL_NEW_REQUIREMENT)

    assert result == {"direction": "INCREASED", "difference": 10.0}


@pytest.mark.parametrize(("attendance", "expected_impact"), EVAL_IMPACT_CASES)
def test_eval_dataset_student_impact_is_deterministic(attendance, expected_impact):
    impact = compare_rules(attendance, EVAL_OLD_REQUIREMENT, EVAL_NEW_REQUIREMENT)

    assert impact == expected_impact


def test_eval_dataset_compare_versions_endpoint(client):
    old_policy = create_verified(
        client, version=EVAL_OLD_VERSION, attendance_requirement=EVAL_OLD_REQUIREMENT
    )
    new_policy = create_verified(
        client, version=EVAL_NEW_VERSION, attendance_requirement=EVAL_NEW_REQUIREMENT
    )

    response = client.post(
        "/compare-versions",
        json={"old_policy_id": old_policy["id"], "new_policy_id": new_policy["id"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["direction"] == "INCREASED"
    assert data["difference"] == 10.0


@pytest.mark.parametrize(("attendance", "expected_impact"), EVAL_IMPACT_CASES)
def test_eval_dataset_student_impact_endpoint(client, attendance, expected_impact):
    old_policy = create_verified(
        client, version=EVAL_OLD_VERSION, attendance_requirement=EVAL_OLD_REQUIREMENT
    )
    new_policy = create_verified(
        client, version=EVAL_NEW_VERSION, attendance_requirement=EVAL_NEW_REQUIREMENT
    )

    response = client.post(
        "/student-impact",
        json={
            "old_policy_id": old_policy["id"],
            "new_policy_id": new_policy["id"],
            "attendance": attendance,
        },
    )

    assert response.status_code == 200
    assert response.json()["impact"] == expected_impact