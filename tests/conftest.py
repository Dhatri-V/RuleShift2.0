"""Shared test configuration for RuleShift.

Provides deterministic admin credentials via environment variables and a
fixture that bypasses admin authentication for tests that are not about
authentication itself.
"""

import os

import pytest

from core.auth import (
    ADMIN_EMAIL_ENV,
    ADMIN_PASSWORD_ENV,
    JWT_SECRET_ENV,
    require_admin,
)

TEST_ADMIN_EMAIL = "admin@ruleshift.test"
TEST_ADMIN_PASSWORD = "test-admin-password"
TEST_JWT_SECRET = "test-jwt-secret"

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