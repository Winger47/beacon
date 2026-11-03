"""FastAPI dependencies: per-request DB session and the authenticated Principal."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from kata_domain.repositories import Principal

from . import auth
from .config import get_settings
from .db import SessionFactory, make_engine, make_session_factory
from .errors import ProblemError


@lru_cache(maxsize=1)
def _session_factory() -> SessionFactory:
    return make_session_factory(make_engine())


def get_session() -> Iterator[Session]:
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_principal(request: Request, session: Session = Depends(get_session)) -> Principal:
    settings = get_settings()

    dev_user = request.headers.get("X-Kata-Dev-User")
    if dev_user and settings.dev_auth:
        principal = auth.principal_from_dev_header(session, dev_user)
        if principal is not None:
            return principal

    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        token = header[len("Bearer ") :].strip()
        if token.startswith(auth.TOKEN_PREFIX):
            principal = auth.principal_from_api_token(session, token)
        else:
            principal = auth.principal_from_jwt(session, token, settings)
        if principal is not None:
            return principal

    raise ProblemError(
        status=401,
        title="Unauthorized",
        detail="A valid API token or OIDC bearer token is required.",
        type_="https://kata.dev/problems/unauthorized",
    )
