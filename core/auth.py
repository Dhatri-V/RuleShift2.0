"""Minimal admin authentication for RuleShift.

A single admin account is configured through environment variables:

- RULESHIFT_ADMIN_EMAIL
- RULESHIFT_ADMIN_PASSWORD
- RULESHIFT_JWT_SECRET

Credentials are never hardcoded, never logged, and never returned by the
API. Password comparison is constant-time. JWTs expire after one hour.
"""

import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


ADMIN_EMAIL_ENV = "RULESHIFT_ADMIN_EMAIL"
ADMIN_PASSWORD_ENV = "RULESHIFT_ADMIN_PASSWORD"
JWT_SECRET_ENV = "RULESHIFT_JWT_SECRET"

JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60

bearer_scheme = HTTPBearer(auto_error=False)


class AdminConfigError(RuntimeError):
    """Raised when the admin environment variables are not configured."""


def _required_env(name):
    value = os.environ.get(name)
    if not value:
        raise AdminConfigError(
            f"Environment variable {name} is not set. "
            "Configure the admin account before using this endpoint."
        )
    return value


def get_admin_email():
    return _required_env(ADMIN_EMAIL_ENV)


def get_admin_password():
    return _required_env(ADMIN_PASSWORD_ENV)


def get_jwt_secret():
    return _required_env(JWT_SECRET_ENV)


def verify_admin_credentials(email, password):
    """Compare both values in constant time; never reveal which part failed."""
    try:
        expected_email = get_admin_email()
        expected_password = get_admin_password()
    except AdminConfigError:
        return False

    email_matches = hmac.compare_digest(
        email.encode("utf-8"),
        expected_email.encode("utf-8"),
    )
    password_matches = hmac.compare_digest(
        password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )
    return email_matches and password_matches


def create_access_token(email):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "role": "admin",
        "iat": now,
        "exp": now + timedelta(minutes=TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token):
    return jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])


def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """FastAPI dependency guarding admin-only endpoints."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except AdminConfigError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin session has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin privileges required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload