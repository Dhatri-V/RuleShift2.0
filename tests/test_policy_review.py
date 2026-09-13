from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app, get_database
from core.auth import require_admin
from conftest import drop_all_test_schema, upload_source_policy
from database.db import Base


FAKE_ANSWER = {
    "answer": "Students must maintain 85% attendance.",
    "evidence": [
        {
            "policy_name": "Academic Attendance Policy",
            "version": "2026",
            "page_number": 1,
            "text": "Students must maintain a minimum attendance of 85%.",
        }
    ],
}



def ask(client, policy_name, version, question="What attendance is required?"):
    return client.post(
        "/ask",
        json={
            "policy_name": policy_name,
            "version": version,
            "question": question,
        },
    )


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
    # These tests cover lifecycle rules, not authentication.
    app.dependency_overrides[require_admin] = lambda: {"sub": "admin", "role": "admin"}
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        drop_all_test_schema(test_engine)
        test_engine.dispose()


def create_draft(
    client,
    version="2026",
    attendance_requirement=80,
    name="Academic Attendance Policy",
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
    assert response.json()["status"] == "DRAFT"
    return response.json()


def create_verified(
    client,
    version="2026",
    attendance_requirement=80,
    name="Academic Attendance Policy",
):
    policy = upload_source_policy(
        client, name=name, version=version, attendance=attendance_requirement,
    )
    response = client.post(f"/policies/{policy['id']}/verify")
    assert response.status_code == 200
    assert response.json()["status"] == "VERIFIED"
    return response.json()


def test_policy_list_exposes_stable_family_ownership(client):
    first = create_draft(client, version="2025", name="Attendance Policy")
    second = create_draft(client, version="2026", name="Attendance Policy")
    other = create_draft(client, version="2027", name="Other Policy")

    rows = {row["id"]: row for row in client.get("/admin/policies").json()}

    assert rows[first["id"]]["family_id"] == rows[second["id"]]["family_id"]
    assert rows[first["id"]]["family_id"] != rows[other["id"]]["family_id"]


def test_source_free_draft_cannot_be_verified(client):
    policy = create_draft(client)
    response = client.post(f"/policies/{policy['id']}/verify")
    assert response.status_code == 409
    assert "authoritative PDF" in response.json()["detail"]


def test_source_backed_draft_can_be_verified(client):
    policy = upload_source_policy(client, attendance=80)
    response = client.post(f"/policies/{policy['id']}/verify")
    assert response.status_code == 200
    assert response.json()["status"] == "VERIFIED"


def test_policy_cannot_be_verified_twice(client):
    policy = upload_source_policy(client, attendance=80)
    first_response = client.post(f"/policies/{policy['id']}/verify")

    second_response = client.post(f"/policies/{policy['id']}/verify")

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["detail"] == "Only DRAFT policies can be verified."


def test_draft_policy_cannot_be_marked_current(client):
    policy = create_draft(client)

    response = client.post(f"/policies/{policy['id']}/mark-current")

    assert response.status_code == 409
    assert response.json()["detail"] == "Only VERIFIED policies can be marked CURRENT."
    assert client.get("/admin/policies").json()[0]["status"] == "DRAFT"


def test_draft_rule_can_be_edited(client):
    policy = upload_source_policy(client, attendance=85.5)

    response = client.patch(
        f"/policies/{policy['id']}/rule",
        json={"attendance_requirement": 85.5},
    )

    assert response.status_code == 200
    assert response.json()["attendance_requirement"] == 85.5
    assert response.json()["status"] == "DRAFT"


def test_rule_cannot_be_edited_after_verification(client):
    policy = create_verified(client)

    response = client.patch(
        f"/policies/{policy['id']}/rule",
        json={"attendance_requirement": 85},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Only DRAFT policies can have their rule edited."


@pytest.mark.parametrize(
    ("attendance_requirement", "expected_status"),
    [
        (0, 200),
        (100, 200),
        (-0.1, 422),
        (100.1, 422),
    ],
)
def test_rule_attendance_requirement_must_be_between_zero_and_one_hundred(
    client,
    attendance_requirement,
    expected_status,
):
    source_value = attendance_requirement if 0 <= attendance_requirement <= 100 else 80
    policy = upload_source_policy(client, attendance=source_value)

    response = client.patch(
        f"/policies/{policy['id']}/rule",
        json={"attendance_requirement": attendance_requirement},
    )

    assert response.status_code == expected_status


def test_marking_verified_policy_current_supersedes_previous_current(client):
    previous_policy = create_verified(client, version="2025")
    client.post(f"/policies/{previous_policy['id']}/mark-current")
    new_policy = create_verified(client, version="2026")

    response = client.post(f"/policies/{new_policy['id']}/mark-current")

    assert response.status_code == 200
    assert response.json()["status"] == "CURRENT"
    assert response.json()["superseded_id"] == previous_policy["id"]
    policies_by_id = {
        policy["id"]: policy for policy in client.get("/admin/policies").json()
    }
    assert policies_by_id[previous_policy["id"]]["status"] == "SUPERSEDED"


def test_compare_versions_shows_increased_requirement(client):
    old_policy = create_verified(client, version="2025", attendance_requirement=75)
    new_policy = create_verified(client, version="2026", attendance_requirement=85)

    response = client.post(
        "/compare-versions",
        json={"old_policy_id": old_policy["id"], "new_policy_id": new_policy["id"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["direction"] == "INCREASED"
    assert data["difference"] == 10.0
    assert data["old_policy"]["attendance_requirement"] == 75
    assert data["new_policy"]["attendance_requirement"] == 85


def test_compare_versions_shows_decreased_requirement(client):
    old_policy = create_verified(client, version="2025", attendance_requirement=85)
    new_policy = create_verified(client, version="2026", attendance_requirement=75)

    response = client.post(
        "/compare-versions",
        json={"old_policy_id": old_policy["id"], "new_policy_id": new_policy["id"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["direction"] == "DECREASED"
    assert data["difference"] == -10.0
    assert data["old_policy"]["attendance_requirement"] == 85
    assert data["new_policy"]["attendance_requirement"] == 75


def test_compare_versions_shows_unchanged_requirement(client):
    old_policy = create_verified(client, version="2025", attendance_requirement=80)
    new_policy = create_verified(client, version="2026", attendance_requirement=80)

    response = client.post(
        "/compare-versions",
        json={"old_policy_id": old_policy["id"], "new_policy_id": new_policy["id"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["direction"] == "UNCHANGED"
    assert data["difference"] == 0.0


def test_compare_versions_rejects_draft_policies(client):
    old_policy = create_verified(client, version="2025", attendance_requirement=75)
    draft_policy = create_draft(client, version="2026", attendance_requirement=85)

    response = client.post(
        "/compare-versions",
        json={"old_policy_id": old_policy["id"], "new_policy_id": draft_policy["id"]},
    )

    assert response.status_code == 409
    assert "DRAFT" in response.json()["detail"]


def test_compare_versions_rejects_same_policy(client):
    policy = create_verified(client, version="2026", attendance_requirement=80)

    response = client.post(
        "/compare-versions",
        json={"old_policy_id": policy["id"], "new_policy_id": policy["id"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Old and new policy versions must be different."


def test_compare_versions_rejects_different_policy_names(client):
    first_policy = create_verified(client, version="2025", attendance_requirement=75)
    second_policy = create_verified(
        client,
        version="2026",
        attendance_requirement=85,
        name="Different Policy",
    )

    response = client.post(
        "/compare-versions",
        json={"old_policy_id": first_policy["id"], "new_policy_id": second_policy["id"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only versions of the same policy can be compared."


def test_compare_versions_returns_not_found(client):
    policy = create_verified(client, version="2026", attendance_requirement=80)

    response = client.post(
        "/compare-versions",
        json={"old_policy_id": policy["id"], "new_policy_id": 999},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Policy id 999 not found."


def student_impact(client, old_policy, new_policy, attendance):
    return client.post(
        "/student-impact",
        json={
            "old_policy_id": old_policy["id"],
            "new_policy_id": new_policy["id"],
            "attendance": attendance,
        },
    )


def test_student_impact_pass_to_pass_is_still_compliant(client):
    old_policy = create_verified(client, version="2025", attendance_requirement=75)
    new_policy = create_verified(client, version="2026", attendance_requirement=85)

    response = student_impact(client, old_policy, new_policy, 90)

    assert response.status_code == 200
    data = response.json()
    assert data["attendance"] == 90
    assert data["old_policy"]["result"] == "PASS"
    assert data["new_policy"]["result"] == "PASS"
    assert data["impact"] == "STILL_COMPLIANT"


def test_student_impact_pass_to_fail_is_newly_non_compliant(client):
    old_policy = create_verified(client, version="2025", attendance_requirement=75)
    new_policy = create_verified(client, version="2026", attendance_requirement=85)

    response = student_impact(client, old_policy, new_policy, 80)

    assert response.status_code == 200
    data = response.json()
    assert data["attendance"] == 80
    assert data["old_policy"]["result"] == "PASS"
    assert data["new_policy"]["result"] == "FAIL"
    assert data["impact"] == "NEWLY_NON_COMPLIANT"


def test_student_impact_fail_to_pass_is_newly_compliant(client):
    old_policy = create_verified(client, version="2025", attendance_requirement=85)
    new_policy = create_verified(client, version="2026", attendance_requirement=75)

    response = student_impact(client, old_policy, new_policy, 80)

    assert response.status_code == 200
    data = response.json()
    assert data["attendance"] == 80
    assert data["old_policy"]["result"] == "FAIL"
    assert data["new_policy"]["result"] == "PASS"
    assert data["impact"] == "NEWLY_COMPLIANT"


def test_student_impact_fail_to_fail_is_still_non_compliant(client):
    old_policy = create_verified(client, version="2025", attendance_requirement=85)
    new_policy = create_verified(client, version="2026", attendance_requirement=75)

    response = student_impact(client, old_policy, new_policy, 70)

    assert response.status_code == 200
    data = response.json()
    assert data["attendance"] == 70
    assert data["old_policy"]["result"] == "FAIL"
    assert data["new_policy"]["result"] == "FAIL"
    assert data["impact"] == "STILL_NON_COMPLIANT"


def test_student_impact_rejects_draft_policy(client):
    old_policy = create_verified(client, version="2025", attendance_requirement=75)
    draft_policy = create_draft(client, version="2026", attendance_requirement=85)

    response = student_impact(client, old_policy, draft_policy, 80)

    assert response.status_code == 409
    assert "DRAFT" in response.json()["detail"]


def test_student_impact_rejects_different_policy_names(client):
    first_policy = create_verified(client, version="2025", attendance_requirement=75)
    second_policy = create_verified(
        client,
        version="2026",
        attendance_requirement=85,
        name="Different Policy",
    )

    response = student_impact(client, first_policy, second_policy, 80)

    assert response.status_code == 400
    assert response.json()["detail"] == "Only versions of the same policy can be compared."


@pytest.mark.parametrize("attendance", [-0.1, 100.1])
def test_student_impact_rejects_invalid_attendance(client, attendance):
    old_policy = create_verified(client, version="2025", attendance_requirement=75)
    new_policy = create_verified(client, version="2026", attendance_requirement=85)

    response = student_impact(client, old_policy, new_policy, attendance)

    assert response.status_code == 422


def test_student_impact_returns_not_found(client):
    policy = create_verified(client, version="2026", attendance_requirement=80)

    response = client.post(
        "/student-impact",
        json={
            "old_policy_id": policy["id"],
            "new_policy_id": 999,
            "attendance": 80,
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Policy id 999 not found."


def test_ask_returns_not_found_for_nonexistent_policy(client):
    response = client.post(
        "/ask",
        json={
            "policy_name": "Nonexistent Policy",
            "version": "2026",
            "question": "What is the attendance requirement?",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Policy 'Nonexistent Policy' version '2026' not found."


def test_ask_rejects_draft_policy(client):
    draft_policy = create_draft(client, version="2026", attendance_requirement=80)

    response = ask(client, draft_policy["name"], draft_policy["version"])

    assert response.status_code == 409
    assert "DRAFT" in response.json()["detail"]


def test_ask_returns_not_found_for_wrong_version(client):
    create_verified(client, version="2025", attendance_requirement=75)

    response = ask(client, "Academic Attendance Policy", "2026")

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Policy 'Academic Attendance Policy' version '2026' not found."
    )


@patch("backend.main.answer_policy_question")
def test_ask_allows_verified_policy(mock_answer, client):
    mock_answer.return_value = dict(FAKE_ANSWER)
    policy = create_verified(client, version="2026", attendance_requirement=85)

    response = ask(client, policy["name"], policy["version"])

    assert response.status_code == 200
    assert response.json()["answer"] == "Students must maintain 85% attendance."
    assert response.json()["evidence"] == FAKE_ANSWER["evidence"]
    mock_answer.assert_called_once_with(
        "Academic Attendance Policy", "2026", "What attendance is required?"
    )


def evidence_for_version(policy_name, version):
    evidence = dict(FAKE_ANSWER["evidence"][0])
    evidence["policy_name"] = policy_name
    evidence["version"] = version
    return {"answer": FAKE_ANSWER["answer"], "evidence": [evidence]}


@patch("backend.main.answer_policy_question")
def test_ask_allows_current_policy(mock_answer, client):
    mock_answer.side_effect = lambda name, version, question: evidence_for_version(
        name, version
    )
    policy = create_verified(client, version="2026", attendance_requirement=85)
    client.post(f"/policies/{policy['id']}/mark-current")

    response = ask(client, policy["name"], policy["version"])

    assert response.status_code == 200
    assert response.json()["evidence"][0]["version"] == "2026"


@patch("backend.main.answer_policy_question")
def test_ask_allows_superseded_policy(mock_answer, client):
    mock_answer.side_effect = lambda name, version, question: evidence_for_version(
        name, version
    )
    old_policy = create_verified(client, version="2025", attendance_requirement=75)
    client.post(f"/policies/{old_policy['id']}/mark-current")
    new_policy = create_verified(client, version="2026", attendance_requirement=85)
    client.post(f"/policies/{new_policy['id']}/mark-current")

    response = ask(client, old_policy["name"], old_policy["version"])

    assert response.status_code == 200
    assert response.json()["evidence"][0]["version"] == "2025"
    mock_answer.assert_called_once_with(
        "Academic Attendance Policy", "2025", "What attendance is required?"
    )


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/policies/999/verify", None),
        ("PATCH", "/policies/999/rule", {"attendance_requirement": 80}),
        ("POST", "/policies/999/mark-current", None),
    ],
)
def test_policy_review_endpoints_return_not_found(client, method, path, payload):
    response = client.request(method, path, json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == "Policy not found."
