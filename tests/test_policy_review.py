import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app, get_database
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
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)
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
    policy = create_draft(
        client,
        version=version,
        attendance_requirement=attendance_requirement,
        name=name,
    )
    response = client.post(f"/policies/{policy['id']}/verify")
    assert response.status_code == 200
    assert response.json()["status"] == "VERIFIED"
    return response.json()


def test_draft_policy_can_be_verified(client):
    policy = create_draft(client)

    response = client.post(f"/policies/{policy['id']}/verify")

    assert response.status_code == 200
    assert response.json()["status"] == "VERIFIED"


def test_policy_cannot_be_verified_twice(client):
    policy = create_draft(client)
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
    assert client.get("/policies").json()[0]["status"] == "DRAFT"


def test_draft_rule_can_be_edited(client):
    policy = create_draft(client)

    response = client.patch(
        f"/policies/{policy['id']}/rule",
        json={"attendance_requirement": 85.5},
    )

    assert response.status_code == 200
    assert response.json()["attendance_requirement"] == 85.5
    assert response.json()["status"] == "DRAFT"


def test_rule_cannot_be_edited_after_verification(client):
    policy = create_draft(client)
    client.post(f"/policies/{policy['id']}/verify")

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
    policy = create_draft(client)

    response = client.patch(
        f"/policies/{policy['id']}/rule",
        json={"attendance_requirement": attendance_requirement},
    )

    assert response.status_code == expected_status


def test_marking_verified_policy_current_supersedes_previous_current(client):
    previous_policy = create_draft(client, version="2025")
    client.post(f"/policies/{previous_policy['id']}/verify")
    client.post(f"/policies/{previous_policy['id']}/mark-current")
    new_policy = create_draft(client, version="2026")
    client.post(f"/policies/{new_policy['id']}/verify")

    response = client.post(f"/policies/{new_policy['id']}/mark-current")

    assert response.status_code == 200
    assert response.json()["status"] == "CURRENT"
    assert response.json()["superseded_id"] == previous_policy["id"]
    policies_by_id = {
        policy["id"]: policy for policy in client.get("/policies").json()
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
