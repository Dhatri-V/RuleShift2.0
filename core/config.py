"""Central configuration for RuleShift.

All backend configuration is read here, once, from the environment (with
optional .env file support via python-dotenv). Secrets are never logged and
never returned by the API.

Values:

- DATABASE_URL              SQLAlchemy database URL
                            (default: sqlite:///./ruleshift.db)
- RULESHIFT_ADMIN_EMAIL     admin login email (required for /auth/login)
- RULESHIFT_ADMIN_PASSWORD  admin login password (required for /auth/login)
- RULESHIFT_JWT_SECRET      JWT signing secret (required for tokens)
- RULESHIFT_JWT_EXPIRE_MINUTES  access-token lifetime in minutes
                            (default: 60)
"""

import os
from functools import lru_cache

try:
    from dotenv import load_dotenv

    # Load a local .env if present; real environment variables always win.
    load_dotenv()
except ImportError:  # pragma: no cover - python-dotenv is in requirements
    pass


DEFAULT_DATABASE_URL = "sqlite:///./ruleshift.db"

DATABASE_URL_ENV = "DATABASE_URL"
ADMIN_EMAIL_ENV = "RULESHIFT_ADMIN_EMAIL"
ADMIN_PASSWORD_ENV = "RULESHIFT_ADMIN_PASSWORD"
JWT_SECRET_ENV = "RULESHIFT_JWT_SECRET"
JWT_EXPIRE_MINUTES_ENV = "RULESHIFT_JWT_EXPIRE_MINUTES"

DEFAULT_JWT_EXPIRE_MINUTES = 60

MAX_UPLOAD_BYTES_ENV = "RULESHIFT_MAX_UPLOAD_BYTES"
CHROMA_PATH_ENV = "RULESHIFT_CHROMA_PATH"
LITELLM_MODEL_ENV = "RULESHIFT_LITELLM_MODEL"
GEMINI_API_KEY_ENV = "RULESHIFT_GEMINI_API_KEY"
EMBEDDING_PROVIDER_ENV = "RULESHIFT_EMBEDDING_PROVIDER"
EMBEDDING_MODEL_ENV = "RULESHIFT_EMBEDDING_MODEL"
DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def get_database_url():
    """Database URL; local SQLite file by default, overridable via env."""
    return os.environ.get(DATABASE_URL_ENV, DEFAULT_DATABASE_URL)


def get_admin_email():
    value = os.environ.get(ADMIN_EMAIL_ENV)
    if not value:
        raise ConfigError(
            f"Environment variable {ADMIN_EMAIL_ENV} is not set. "
            "Configure the admin account before using this endpoint."
        )
    return value


def get_admin_password():
    value = os.environ.get(ADMIN_PASSWORD_ENV)
    if not value:
        raise ConfigError(
            f"Environment variable {ADMIN_PASSWORD_ENV} is not set. "
            "Configure the admin account before using this endpoint."
        )
    return value


def get_jwt_secret():
    value = os.environ.get(JWT_SECRET_ENV)
    if not value:
        raise ConfigError(
            f"Environment variable {JWT_SECRET_ENV} is not set. "
            "Configure a JWT secret before using this endpoint."
        )
    return value


def get_max_upload_bytes():
    """Maximum accepted upload size in bytes (default 10 MB)."""
    raw = os.environ.get(MAX_UPLOAD_BYTES_ENV)
    if not raw:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        limit = int(raw)
    except ValueError:
        raise ConfigError(
            f"Environment variable {MAX_UPLOAD_BYTES_ENV} must be an integer."
        )
    if limit <= 0:
        raise ConfigError(
            f"Environment variable {MAX_UPLOAD_BYTES_ENV} must be positive."
        )
    return limit


def get_chroma_path():
    return os.environ.get(CHROMA_PATH_ENV, "./chroma_db")


def get_litellm_model():
    return os.environ.get(LITELLM_MODEL_ENV, "gemini/gemini-3.5-flash-lite")


def get_litellm_api_key():
    return get_gemini_api_key()


def get_gemini_api_key():
    value = os.environ.get(GEMINI_API_KEY_ENV)
    if not value:
        raise ConfigError(
            f"Environment variable {GEMINI_API_KEY_ENV} is not set. "
            "Configure Gemini before using generation, indexing, or retrieval."
        )
    return value


def get_embedding_provider():
    return os.environ.get(EMBEDDING_PROVIDER_ENV, "google").strip().lower()


def get_embedding_model():
    return os.environ.get(EMBEDDING_MODEL_ENV, "gemini-embedding-001")


def get_embedding_api_key():
    return get_gemini_api_key()


def get_embedding_identity():
    return f"{get_embedding_provider()}:{get_embedding_model()}"


def get_jwt_expire_minutes():
    raw = os.environ.get(JWT_EXPIRE_MINUTES_ENV)
    if not raw:
        return DEFAULT_JWT_EXPIRE_MINUTES
    try:
        minutes = int(raw)
    except ValueError:
        raise ConfigError(
            f"Environment variable {JWT_EXPIRE_MINUTES_ENV} must be an integer."
        )
    if minutes <= 0:
        raise ConfigError(
            f"Environment variable {JWT_EXPIRE_MINUTES_ENV} must be positive."
        )
    return minutes


@lru_cache(maxsize=1)
def get_settings():
    """Snapshot of non-secret settings for diagnostics.

    Deliberately excludes the admin password and JWT secret.
    """
    return {
        "database_url": get_database_url(),
        "admin_email_configured": bool(os.environ.get(ADMIN_EMAIL_ENV)),
        "admin_password_configured": bool(os.environ.get(ADMIN_PASSWORD_ENV)),
        "jwt_secret_configured": bool(os.environ.get(JWT_SECRET_ENV)),
        "jwt_expire_minutes": get_jwt_expire_minutes(),
    }
