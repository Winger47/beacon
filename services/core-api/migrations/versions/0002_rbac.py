"""rbac: app_user, product/type members, user_product_access, api_token (project.md 2.8, 3.10)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from kata_domain import Base
from kata_domain import models as _models  # noqa: F401

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "app_user",
    "product_type_member",
    "product_member",
    "user_product_access",
    "api_token",
)


def _tables() -> list:  # type: ignore[type-arg]
    md = Base.metadata
    return [md.tables[f"core.{name}"] for name in _TABLES]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=_tables())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=list(reversed(_tables())))
