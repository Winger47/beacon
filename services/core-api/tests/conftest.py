"""Pytest fixtures for core-api integration tests.

Each test runs inside a transaction that is rolled back at the end, so the database is
never left dirty. If no database is reachable (e.g. unit-only CI), the tests skip.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from kata_core_api.config import get_settings


@pytest.fixture(scope="session")
def engine() -> Engine:
    eng = create_engine(get_settings().database_url, future=True)
    try:
        conn = eng.connect()
        conn.close()
    except OperationalError:
        pytest.skip("no database reachable (set KATA_DATABASE_URL and run migrations)")
    return eng


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    trans = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()
