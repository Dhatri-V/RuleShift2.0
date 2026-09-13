"""Release-blocker regressions for trust, temporal isolation, and evidence."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app, get_database
from conftest import drop_all_test_schema, upload_source_policy
from core.auth import require_admin
from database.decision_models import ImpactRun
from database.db import Base
from database.models import AuditEvent, PolicyVersion
from services.index_service import rebuild_version_index


@pytest.fixture()
def system():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    def database():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_database] = database
    app.dependency_overrides[require_admin] = lambda: {"sub": "admin", "role": "admin"}
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(client=client, sessions=sessions)
    finally:
        app.dependency_overrides.clear()
        drop_all_test_schema(engine)
        engine.dispose()


def verify(system, version, value, name="Attendance Policy"):
    policy = upload_source_policy(system.client, name=name, version=version, attendance=value)
    response = system.client.post(f"/policies/{policy['id']}/verify")
    assert response.status_code == 200, response.text
    return response.json()


def publish(system, policy):
    response = system.client.post(f"/policies/{policy['id']}/mark-current")
    assert response.status_code == 200, response.text
    return response.json()


def test_source_free_version_fails_verification_and_records_reason(system):
    draft = system.client.post("/policies", json={
        "name": "Attendance Policy", "version": "2026", "attendance_requirement": 85,
    }).json()
    response = system.client.post(f"/policies/{draft['id']}/verify")
    assert response.status_code == 409
    assert "authoritative PDF" in response.json()["detail"]
    with system.sessions() as database:
        record = database.get(PolicyVersion, draft["id"])
        assert record.status == "DRAFT"
        event = database.query(AuditEvent).filter_by(version_id=record.id, action="VERIFICATION_BLOCKED").one()
        assert "authoritative PDF" in event.reason


def test_public_catalogue_excludes_drafts_but_admin_catalogue_includes_them(system):
    draft = system.client.post("/policies", json={
        "name": "Attendance Policy", "version": "draft", "attendance_requirement": 85,
    }).json()
    reviewed = verify(system, "2026", 85)
    assert {row["id"] for row in system.client.get("/policies").json()} == {reviewed["id"]}
    assert {row["id"] for row in system.client.get("/admin/policies").json()} == {draft["id"], reviewed["id"]}


def test_current_ask_resolves_in_sql_and_never_calls_superseded_version(system):
    old = verify(system, "2025", 75)
    publish(system, old)
    new = verify(system, "2026", 85)
    publish(system, new)
    grounded = {
        "answer": "The minimum attendance requirement is 85%.",
        "answer_state": "ANSWERED", "citations": [], "evidence": [],
    }
    with patch("backend.main.answer_policy_question", return_value=grounded) as answer:
        response = system.client.post("/ask", json={
            "policy_name": "Attendance Policy", "question": "What attendance is required?",
        })
    assert response.status_code == 200
    assert response.json()["resolved_policy"]["version"] == "2026"
    assert response.json()["resolved_policy"]["status"] == "CURRENT"
    answer.assert_called_once_with("Attendance Policy", "2026", "What attendance is required?")


def test_publication_fails_closed_when_vector_index_is_missing(system, isolated_default_vector_store):
    policy = verify(system, "2026", 85)
    isolated_default_vector_store.rows.clear()
    response = system.client.post(f"/policies/{policy['id']}/mark-current")
    assert response.status_code == 409
    assert "vector index mismatch" in response.json()["detail"]
    with system.sessions() as database:
        assert database.get(PolicyVersion, policy["id"]).status == "VERIFIED"


def test_verification_records_individual_approved_rule_review(system):
    policy = verify(system, "2026", 85)
    with system.sessions() as database:
        version = database.get(PolicyVersion, policy["id"])
        review = version.rules[0].review
        assert review.status == "APPROVED"
        assert review.reviewer_id == "admin"
        assert review.rule_snapshot["source_clause_id"] == version.rules[0].source_clause_id


def test_publication_rejects_older_verified_version(system):
    current = verify(system, "2027", 85)
    publish(system, current)
    older = verify(system, "2026", 80)
    response = system.client.post(f"/policies/{older['id']}/mark-current")
    assert response.status_code == 409
    assert "not chronologically newer" in response.json()["detail"]
    with system.sessions() as database:
        assert database.get(PolicyVersion, current["id"]).status == "CURRENT"
        assert database.get(PolicyVersion, older["id"]).status == "VERIFIED"


def test_derived_index_can_be_rebuilt_from_authoritative_clauses(system, isolated_default_vector_store):
    policy = verify(system, "2026", 85)
    isolated_default_vector_store.rows.clear()
    with system.sessions() as database:
        version = database.get(PolicyVersion, policy["id"])
        generation = rebuild_version_index(database, version)
        database.commit()
        assert generation.generation == 2
        assert generation.status == "READY"
        assert generation.completed_at is not None
        assert generation.observed_chunk_count == len(version.clauses)
    rows = isolated_default_vector_store.get(where={"version_id": {"$eq": policy["id"]}})
    assert len(rows["ids"]) == 1
    assert rows["metadatas"][0]["clause_id"] is not None


def test_compare_rejects_reverse_chronology_and_cross_family(system):
    old = verify(system, "2026", 85)
    older = verify(system, "2025", 75)
    reverse = system.client.post("/compare-versions", json={
        "old_policy_id": old["id"], "new_policy_id": older["id"],
    })
    assert reverse.status_code == 409
    assert "chronologically newer" in reverse.json()["detail"]
    other = verify(system, "2027", 90, name="Other Attendance Policy")
    cross = system.client.post("/compare-versions", json={
        "old_policy_id": older["id"], "new_policy_id": other["id"],
    })
    assert cross.status_code == 400


def test_impact_persists_immutable_old_and_new_source_snapshots(system):
    old = verify(system, "2025", 75)
    new = verify(system, "2026", 85)
    response = system.client.post("/student-impact", json={
        "old_policy_id": old["id"], "new_policy_id": new["id"], "attendance": 80,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["impact"] == "NEWLY_NON_COMPLIANT"
    assert data["old_policy"]["evidence"]["value"] == 75
    assert data["new_policy"]["evidence"]["value"] == 85
    assert data["old_policy"]["evidence"]["clause_id"]
    assert data["new_policy"]["evidence"]["source_sha256"]
    historical = system.client.get(f"/impact-runs/{data['run_id']}").json()
    assert historical["old_evidence"] == data["old_policy"]["evidence"]
    assert historical["new_evidence"] == data["new_policy"]["evidence"]
    with system.sessions() as database:
        run = database.get(ImpactRun, data["run_id"])
        run.impact = "TAMPERED"
        with pytest.raises(IntegrityError):
            database.commit()
