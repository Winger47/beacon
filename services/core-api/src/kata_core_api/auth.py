"""Authentication: scoped API tokens and OIDC (Keycloak) JWTs → a domain Principal.

Two credential types resolve to the same ``Principal`` used by the repository layer:
  * API token: ``Authorization: Bearer kata_<secret>`` — SHA-256 hashed and looked up.
  * OIDC JWT:  ``Authorization: Bearer <jwt>`` — verified against cached Keycloak JWKS.
A dev-only ``X-Kata-Dev-User`` header is honoured when ``KATA_DEV_AUTH=true`` (local only).
"""

from __future__ import annotations

import datetime
import hashlib
import secrets
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from kata_domain.enums import Role
from kata_domain.models import ApiToken, AppUser
from kata_domain.repositories import Principal

from .config import Settings, get_settings

TOKEN_PREFIX = "kata_"


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_token() -> tuple[str, str]:
    """Return (raw_token_shown_once, sha256_hash_stored)."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def create_api_token(
    session: Session,
    *,
    user_id: int,
    name: str,
    scope_product_ids: list[int] | None = None,
    scope_actions: list[str] | None = None,
    expires_at: datetime.datetime | None = None,
) -> tuple[ApiToken, str]:
    raw, token_hash = generate_token()
    token = ApiToken(
        user_id=user_id,
        name=name,
        token_hash=token_hash,
        scope_product_ids=scope_product_ids or [],
        scope_actions=scope_actions or [],
        expires_at=expires_at,
    )
    session.add(token)
    session.flush()
    return token, raw


def _principal_for_user(user: AppUser) -> Principal:
    role = Role(user.global_role) if user.global_role else None
    return Principal(user_id=user.id, global_role=role)


def principal_from_api_token(session: Session, raw: str) -> Principal | None:
    token = session.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(raw)))
    if token is None or token.revoked_at is not None:
        return None
    now = datetime.datetime.now(tz=datetime.UTC)
    if token.expires_at is not None and token.expires_at < now:
        return None
    token.last_used_at = now
    user = session.get(AppUser, token.user_id)
    if user is None or not user.is_active:
        return None
    return _principal_for_user(user)


@lru_cache(maxsize=1)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


def verify_jwt(token: str, settings: Settings) -> dict[str, Any]:
    """Verify a Keycloak JWT against cached JWKS. Raises jwt.PyJWTError on failure."""
    signing_key = _jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token)
    claims: dict[str, Any] = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.oidc_audience,
        issuer=settings.oidc_issuer,
    )
    return claims


def _get_or_create_user(session: Session, *, subject: str, username: str, email: str | None,
                        global_role: str | None) -> AppUser:
    user = session.scalar(select(AppUser).where(AppUser.subject == subject))
    if user is None:
        user = AppUser(subject=subject, username=username, email=email, global_role=global_role)
        session.add(user)
        session.flush()
    return user


def principal_from_jwt(session: Session, token: str, settings: Settings) -> Principal | None:
    try:
        claims = verify_jwt(token, settings)
    except jwt.PyJWTError:
        return None
    subject = claims.get("sub")
    if not subject:
        return None
    user = _get_or_create_user(
        session,
        subject=subject,
        username=claims.get("preferred_username", subject),
        email=claims.get("email"),
        global_role=claims.get("kata_global_role"),
    )
    return _principal_for_user(user)


def principal_from_dev_header(session: Session, subject: str) -> Principal | None:
    settings = get_settings()
    if not settings.dev_auth:
        return None
    user = _get_or_create_user(
        session,
        subject=subject,
        username=subject,
        email=None,
        global_role=settings.dev_auth_global_role,
    )
    return _principal_for_user(user)
