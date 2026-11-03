"""core schema: hierarchy, findings, test_import, audit_log (project.md 3.2 subset)

Revision ID: 0001
Revises:
Create Date: 2026-11-03

Builds the initial `core` schema. The tables/indexes/constraints are created from the
kata_domain metadata, so the DB matches the ORM models exactly. The enum types and the
audit_log monthly partitions are created explicitly (metadata-create cannot express them).
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence

from alembic import op

from kata_domain import Base
from kata_domain import models as _models  # noqa: F401  (registers tables on metadata)

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _month_bounds(day: datetime.date) -> tuple[str, str]:
    start = day.replace(day=1)
    nxt = (start + datetime.timedelta(days=32)).replace(day=1)
    return start.isoformat(), nxt.isoformat()


def upgrade() -> None:
    bind = op.get_bind()

    op.execute("CREATE SCHEMA IF NOT EXISTS core")

    # Enum types (models reference these with create_type=False).
    op.execute(
        "CREATE TYPE core.severity AS ENUM "
        "('info', 'low', 'medium', 'high', 'critical')"
    )
    op.execute(
        "CREATE TYPE core.finding_status AS ENUM "
        "('active', 'mitigated', 'false_positive', 'out_of_scope', "
        "'risk_accepted', 'under_review')"
    )

    # All core tables, indexes and constraints, straight from the ORM metadata.
    # audit_log is emitted as a PARTITION BY RANGE parent (postgresql_partition_by).
    Base.metadata.create_all(bind=bind)

    # Child partitions for audit_log: a DEFAULT catch-all (so inserts never fail) plus
    # the current month. A scheduler job provisions future months in Phase 6.
    op.execute("CREATE TABLE core.audit_log_default PARTITION OF core.audit_log DEFAULT")
    start, nxt = _month_bounds(datetime.date.today())
    op.execute(
        f"CREATE TABLE core.audit_log_{start[:7].replace('-', '')} "
        f"PARTITION OF core.audit_log FOR VALUES FROM ('{start}') TO ('{nxt}')"
    )


def downgrade() -> None:
    bind = op.get_bind()
    # Dropping the partitioned parent drops its child partitions.
    Base.metadata.drop_all(bind=bind)
    op.execute("DROP TYPE IF EXISTS core.finding_status")
    op.execute("DROP TYPE IF EXISTS core.severity")
    op.execute("DROP SCHEMA IF EXISTS core CASCADE")
