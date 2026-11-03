"""Database engine and session factory for core-api."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


def make_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url, echo=settings.sql_echo, future=True)


SessionFactory = sessionmaker[Session]


def make_session_factory(engine: Engine | None = None) -> SessionFactory:
    return sessionmaker(bind=engine or make_engine(), expire_on_commit=False)


@contextmanager
def session_scope(factory: SessionFactory) -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on error."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
