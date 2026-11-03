"""Declarative base and shared metadata for the Kata `core` schema.

All ORM models live under this base. A consistent constraint/index naming convention
keeps Alembic autogenerate deterministic across future migrations.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic names for constraints and indexes (important for stable migrations).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

CORE_SCHEMA = "core"


class Base(DeclarativeBase):
    """Declarative base for all `core` schema models."""

    metadata = MetaData(schema=CORE_SCHEMA, naming_convention=NAMING_CONVENTION)
