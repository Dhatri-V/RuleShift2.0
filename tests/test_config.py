"""Focused tests for the central configuration layer (core/config.py)."""

import pytest

from core.config import (
    ADMIN_EMAIL_ENV,
    ADMIN_PASSWORD_ENV,
    DATABASE_URL_ENV,
    DEFAULT_DATABASE_URL,
    DEFAULT_JWT_EXPIRE_MINUTES,
    JWT_EXPIRE_MINUTES_ENV,
    JWT_SECRET_ENV,
    ConfigError,
    get_admin_email,
    get_admin_password,
    get_database_url,
    get_jwt_expire_minutes,
    get_jwt_secret,
    get_settings,
)


@pytest.fixture()
def clean_env(monkeypatch):
    """Remove all RuleShift config variables for isolated config tests."""
    for name in (
        DATABASE_URL_ENV,
        ADMIN_EMAIL_ENV,
        ADMIN_PASSWORD_ENV,
        JWT_SECRET_ENV,
        JWT_EXPIRE_MINUTES_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_default_database_url_is_local_sqlite(clean_env):
    assert get_database_url() == "sqlite:///./ruleshift.db"
    assert DEFAULT_DATABASE_URL == "sqlite:///./ruleshift.db"


def test_database_url_env_override_works(clean_env):
    clean_env.setenv(DATABASE_URL_ENV, "sqlite:////tmp/other.db")

    assert get_database_url() == "sqlite:////tmp/other.db"


def test_admin_values_read_from_environment(clean_env):
    clean_env.setenv(ADMIN_EMAIL_ENV, "boss@example.edu")
    clean_env.setenv(ADMIN_PASSWORD_ENV, "s3cret!")
    clean_env.setenv(JWT_SECRET_ENV, "top-secret")

    assert get_admin_email() == "boss@example.edu"
    assert get_admin_password() == "s3cret!"
    assert get_jwt_secret() == "top-secret"


def test_missing_admin_email_fails_safely(clean_env):
    clean_env.setenv(ADMIN_PASSWORD_ENV, "s3cret!")
    clean_env.setenv(JWT_SECRET_ENV, "top-secret")

    with pytest.raises(ConfigError) as error:
        get_admin_email()

    assert ADMIN_EMAIL_ENV in str(error.value)


def test_missing_admin_password_fails_safely(clean_env):
    clean_env.setenv(ADMIN_EMAIL_ENV, "boss@example.edu")
    clean_env.setenv(JWT_SECRET_ENV, "top-secret")

    with pytest.raises(ConfigError) as error:
        get_admin_password()

    assert ADMIN_PASSWORD_ENV in str(error.value)


def test_missing_jwt_secret_fails_safely(clean_env):
    clean_env.setenv(ADMIN_EMAIL_ENV, "boss@example.edu")
    clean_env.setenv(ADMIN_PASSWORD_ENV, "s3cret!")

    with pytest.raises(ConfigError) as error:
        get_jwt_secret()

    assert JWT_SECRET_ENV in str(error.value)


def test_jwt_expiry_defaults_to_sixty_minutes(clean_env):
    assert get_jwt_expire_minutes() == 60
    assert get_jwt_expire_minutes() == DEFAULT_JWT_EXPIRE_MINUTES


def test_jwt_expiry_env_override(clean_env):
    clean_env.setenv(JWT_EXPIRE_MINUTES_ENV, "15")

    assert get_jwt_expire_minutes() == 15


@pytest.mark.parametrize("raw", ["abc", "0", "-5"])
def test_invalid_jwt_expiry_fails_safely(clean_env, raw):
    clean_env.setenv(JWT_EXPIRE_MINUTES_ENV, raw)

    with pytest.raises(ConfigError):
        get_jwt_expire_minutes()


def test_settings_snapshot_never_exposes_secrets(clean_env):
    clean_env.setenv(ADMIN_EMAIL_ENV, "boss@example.edu")
    clean_env.setenv(ADMIN_PASSWORD_ENV, "s3cret-value")
    clean_env.setenv(JWT_SECRET_ENV, "secret-value")

    settings = get_settings()

    assert "s3cret-value" not in str(settings)
    assert "secret-value" not in str(settings)
    assert settings["admin_password_configured"] is True
    assert settings["jwt_secret_configured"] is True
    assert "password" not in settings
    assert "secret" not in settings


def test_verify_admin_credentials_fail_safely_without_config(clean_env):
    from core.auth import verify_admin_credentials

    assert verify_admin_credentials("any@example.com", "anything") is False