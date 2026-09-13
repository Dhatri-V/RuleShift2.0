"""Shared test configuration for RuleShift.

Provides deterministic admin credentials via environment variables and a
fixture that bypasses admin authentication for tests that are not about
authentication itself.
"""

import os

import pytest

from core.auth import require_admin
from core.config import (
    ADMIN_EMAIL_ENV,
    ADMIN_PASSWORD_ENV,
    JWT_SECRET_ENV,
)

TEST_ADMIN_EMAIL = "admin@ruleshift.test"
TEST_ADMIN_PASSWORD = "test-admin-password"
TEST_JWT_SECRET = "test-jwt-secret-with-at-least-32-bytes"

# Set before any test module imports backend.main.
os.environ[ADMIN_EMAIL_ENV] = TEST_ADMIN_EMAIL
os.environ[ADMIN_PASSWORD_ENV] = TEST_ADMIN_PASSWORD
os.environ[JWT_SECRET_ENV] = TEST_JWT_SECRET


@pytest.fixture()
def admin_headers():
    """Authorization header carrying a valid admin token."""
    from core.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token(TEST_ADMIN_EMAIL)}"}


@pytest.fixture()
def bypass_admin_auth():
    """Override the require_admin dependency so lifecycle tests can focus
    on lifecycle rules instead of authentication."""
    from backend.main import app

    app.dependency_overrides[require_admin] = lambda: {"sub": TEST_ADMIN_EMAIL, "role": "admin"}
    yield
    app.dependency_overrides.pop(require_admin, None)

def make_attendance_pdf(attendance):
    """Small real source document used by lifecycle tests."""
    import pymupdf
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text(
            (72, 72),
            f"3.1 Attendance\nThe minimum attendance requirement is {attendance}% in each course.",
        )
        return document.tobytes()


def upload_source_policy(client, *, name="Academic Attendance Policy", version="2026", attendance=80, headers=None):
    response = client.post(
        "/policies/upload",
        headers=headers or {},
        data={"policy_name": name, "version": version},
        files={"file": (f"attendance-{version}.pdf", make_attendance_pdf(attendance), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    return response.json()


class MemoryVectorStore:
    """Deterministic default test store; prevents tests touching ./chroma_db."""
    def __init__(self):
        self.rows = {}

    def add_documents(self, documents, ids):
        for identifier, document in zip(ids, documents):
            self.rows[identifier] = document
        return list(ids)

    @staticmethod
    def _matches(metadata, where):
        if not where:
            return True
        if "$and" in where:
            return all(MemoryVectorStore._matches(metadata, item) for item in where["$and"])
        for key, condition in where.items():
            expected = condition.get("$eq") if isinstance(condition, dict) else condition
            if metadata.get(key) != expected:
                return False
        return True

    def delete(self, ids=None, where=None):
        selected = list(ids or [
            identifier for identifier, document in self.rows.items()
            if self._matches(document.metadata, where)
        ])
        for identifier in selected:
            self.rows.pop(identifier, None)

    def get(self, where=None, include=None):
        pairs = [
            (identifier, document) for identifier, document in self.rows.items()
            if self._matches(document.metadata, where)
        ]
        return {
            "ids": [identifier for identifier, _ in pairs],
            "documents": [document.page_content for _, document in pairs],
            "metadatas": [document.metadata for _, document in pairs],
        }

    def similarity_search(self, question, k=4, filter=None):
        return [
            document for document in self.rows.values()
            if self._matches(document.metadata, filter)
        ][:k]


@pytest.fixture(autouse=True)
def isolated_default_vector_store(monkeypatch):
    """No backend test may accidentally open the repository's live Chroma path."""
    import ai.rag
    store = MemoryVectorStore()
    monkeypatch.setattr(ai.rag, "get_vector_store", lambda: store)
    return store


def drop_all_test_schema(engine):
    """Drop self-referential policy tables in SQLite test databases."""
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    from database.db import Base
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
