"""dedup + reimport: match_key/cross_tool_hash, ingest staging, reimport_decision (Phase 3)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-06

Adds the Phase 3 deduplication/reimport machinery (project.md 3.7, ADR-0011/0012/0013):

- ``core.finding.match_key`` and ``core.finding.cross_tool_hash`` + their indexes.
- ``core.reimport_decision`` (mass-closure circuit-breaker pending state).
- The ``ingest`` schema with ``reimport_seen`` and ``applied_batch`` UNLOGGED staging tables
  (3.2/3.7.4). These are intentionally NOT on the ORM ``Base`` metadata (they are the
  ingestion plane's, not the core domain's), so they are created here explicitly.

Every statement is idempotent (IF [NOT] EXISTS). On a *fresh* database, migration 0001's
``create_all`` already builds the finding columns/indexes and ``reimport_decision`` from the
current models, so this revision only needs to add the ``ingest`` objects; on an existing
database it adds everything. Idempotency lets the same script serve both.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- core.finding: dedup/reimport keys -----------------------------------
    op.execute("ALTER TABLE core.finding ADD COLUMN IF NOT EXISTS match_key text")
    op.execute("ALTER TABLE core.finding ADD COLUMN IF NOT EXISTS cross_tool_hash varchar(64)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS finding_test_matchkey "
        "ON core.finding (test_id, match_key)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS finding_product_crosshash "
        "ON core.finding (product_id, cross_tool_hash) "
        "WHERE duplicate_of IS NULL AND cross_tool_hash IS NOT NULL"
    )

    # --- core.reimport_decision ----------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS core.reimport_decision (
            import_job_id         varchar(36) PRIMARY KEY,
            test_id               bigint NOT NULL REFERENCES core.test(id),
            status                text NOT NULL DEFAULT 'needs_confirmation',
            close_candidate_ids   bigint[] NOT NULL DEFAULT '{}',
            active_before         integer NOT NULL,
            incoming_count        integer NOT NULL,
            previous_import_count integer NOT NULL,
            created_at            timestamptz NOT NULL DEFAULT now(),
            resolved_at           timestamptz,
            CONSTRAINT reimport_decision_status_valid
                CHECK (status IN ('needs_confirmation','confirmed','rejected'))
        )
        """
    )

    # --- ingest staging (UNLOGGED: fast, not crash-safe; see project.md 3.2 Think-first) -----
    op.execute("CREATE SCHEMA IF NOT EXISTS ingest")
    op.execute(
        """
        CREATE UNLOGGED TABLE IF NOT EXISTS ingest.reimport_seen (
            job_id    varchar(36) NOT NULL,
            match_key text NOT NULL,
            PRIMARY KEY (job_id, match_key)
        )
        """
    )
    op.execute(
        """
        CREATE UNLOGGED TABLE IF NOT EXISTS ingest.applied_batch (
            job_id     varchar(36) NOT NULL,
            seq        integer NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (job_id, seq)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS ingest CASCADE")
    op.execute("DROP TABLE IF EXISTS core.reimport_decision")
    op.execute("DROP INDEX IF EXISTS core.finding_product_crosshash")
    op.execute("DROP INDEX IF EXISTS core.finding_test_matchkey")
    op.execute("ALTER TABLE core.finding DROP COLUMN IF EXISTS cross_tool_hash")
    op.execute("ALTER TABLE core.finding DROP COLUMN IF EXISTS match_key")
