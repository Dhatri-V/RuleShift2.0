"""Focused tests for minimal admin authentication and authorization.

Covers: login success/failure, token protection on admin endpoints,
invalid/expired tokens, and that public endpoints stay public.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app, get_database
from conftest import TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD
from core.auth import JWT_ALGORITHM
from core.config import DEFAULT_JWT_EXPIRE_MINUTES
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


def login(client, email=TEST_ADMIN_EMAIL, password=TEST_ADMIN_PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def create_draft(client, version="2026", attendance_requirement=80):
    """Create a DRAFT policy as the admin (POST /policies is admin-only)."""
    token = login(client).json()["access_token"]
    response = client.post(
        "/policies",
        json={
            "name": "Academic Attendance Policy",
            "version": version,
            "attendance_requirement": attendance_requirement,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_correct_login_returns_token(client):
    response = login(client)

    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert isinstance(data["access_token"], str)
    assert data["access_token"].count(".") == 2  # header.payload.signature


def test_wrong_password_rejected(client):
    response = login(client, password="not-the-password")

    assert response.status_code == 401
    assert "Invalid admin email or password" in response.json()["detail"]


def test_wrong_email_rejected(client):
    response = login(client, email="intruder@ruleshift.test")

    assert response.status_code == 401
    assert "Invalid admin email or password" in response.json()["detail"]


def test_login_response_never_contains_password(client):
    response = login(client)

    assert "password" not in response.text.lower().replace("access_token", "")


def test_token_contains_expiry_and_admin_role(client):
    response = login(client)

    import jwt

    from core.auth import get_jwt_secret

    payload = jwt.decode(
        response.json()["access_token"],
        get_jwt_secret(),
        algorithms=[JWT_ALGORITHM],
    )
    assert payload["role"] == "admin"
    assert payload["sub"] == TEST_ADMIN_EMAIL
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
    assert exp - iat == timedelta(minutes=DEFAULT_JWT_EXPIRE_MINUTES)


# ---------------------------------------------------------------------------
# Protected admin endpoints
# ---------------------------------------------------------------------------


def test_verify_without_token_rejected(client):
    policy = create_draft(client)

    response = client.post(f"/policies/{policy['id']}/verify")

    assert response.status_code == 401


def test_verify_with_invalid_token_rejected(client):
    policy = create_draft(client)

    response = client.post(
        f"/policies/{policy['id']}/verify",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401


def test_verify_with_expired_token_rejected(client):
    import jwt

    from core.auth import get_jwt_secret

    policy = create_draft(client)
    expired = jwt.encode(
        {
            "sub": TEST_ADMIN_EMAIL,
            "role": "admin",
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        },
        get_jwt_secret(),
        algorithm=JWT_ALGORITHM,
    )

    response = client.post(
        f"/policies/{policy['id']}/verify",
        headers={"Authorization": f"Bearer {expired}"},
    )

    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_verify_with_valid_token_works(client):
    policy = create_draft(client)
    token = login(client).json()["access_token"]

    response = client.post(
        f"/policies/{policy['id']}/verify",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "VERIFIED"


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/policies", {"name": "P", "version": "1", "attendance_requirement": 80}),
        ("PATCH", "/policies/1/rule", {"attendance_requirement": 80}),
        ("PATCH", "/policies/1/status", {"status": "SUPERSEDED"}),
        ("POST", "/policies/1/verify", None),
        ("POST", "/policies/1/mark-current", None),
    ],
)
def test_all_admin_endpoints_require_token(client, method, path, payload):
    response = client.request(method, path, json=payload)

    assert response.status_code == 401


def test_upload_requires_token(client):
    response = client.post(
        "/policies/upload",
        data={"policy_name": "P", "version": "1"},
        files={"file": ("policy.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 401


def test_token_signed_with_wrong_secret_rejected(client):
    import jwt

    policy = create_draft(client)
    forged = jwt.encode(
        {
            "sub": TEST_ADMIN_EMAIL,
            "role": "admin",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "attacker-controlled-secret",
        algorithm=JWT_ALGORITHM,
    )

    response = client.post(
        f"/policies/{policy['id']}/verify",
        headers={"Authorization": f"Bearer {forged}"},
    )

    assert response.status_code == 401


def test_token_without_admin_role_rejected(client):
    import jwt

    from core.auth import get_jwt_secret

    policy = create_draft(client)
    non_admin = jwt.encode(
        {
            "sub": TEST_ADMIN_EMAIL,
            "role": "student",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        get_jwt_secret(),
        algorithm=JWT_ALGORITHM,
    )

    response = client.post(
        f"/policies/{policy['id']}/verify",
        headers={"Authorization": f"Bearer {non_admin}"},
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Public endpoints stay public
# ---------------------------------------------------------------------------


def test_policy_list_is_public(client):
    create_draft(client)

    response = client.get("/policies")

    assert response.status_code == 200
    assert len(response.json()) == 1


@patch("backend.main.answer_policy_question")
def test_ask_is_public_without_login(mock_answer, client):
    mock_answer.return_value = {"answer": "85%", "evidence": []}
    policy = create_draft(client)
    client.post(
        f"/policies/{policy['id']}/verify",
        headers={"Authorization": f"Bearer {login(client).json()['access_token']}"},
    )

    response = client.post(
        "/ask",
        json={
            "policy_name": policy["name"],
            "version": policy["version"],
            "question": "What attendance is required?",
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "85%"


def test_compare_versions_is_public_without_login(client):
    draft = create_draft(client, version="2025", attendance_requirement=75)
    client.post(
        f"/policies/{draft['id']}/verify",
        headers={"Authorization": f"Bearer {login(client).json()['access_token']}"},
    )
    draft2 = create_draft(client, version="2026", attendance_requirement=85)
    client.post(
        f"/policies/{draft2['id']}/verify",
        headers={"Authorization": f"Bearer {login(client).json()['access_token']}"},
    )

    response = client.post(
        "/compare-versions",
        json={"old_policy_id": draft["id"], "new_policy_id": draft2["id"]},
    )

    assert response.status_code == 200
    assert response.json()["direction"] == "INCREASED"


def test_student_impact_is_public_without_login(client):
    draft = create_draft(client, version="2025", attendance_requirement=75)
    token = login(client).json()["access_token"]
    client.post(f"/policies/{draft['id']}/verify", headers={"Authorization": f"Bearer {token}"})
    draft2 = create_draft(client, version="2026", attendance_requirement=85)
    client.post(f"/policies/{draft2['id']}/verify", headers={"Authorization": f"Bearer {token}"})

    response = client.post(
        "/student-impact",
        json={
            "old_policy_id": draft["id"],
            "new_policy_id": draft2["id"],
            "attendance": 80,
        },
    )

    assert response.status_code == 200
    assert response.json()["impact"] == "NEWLY_NON_COMPLIANT"