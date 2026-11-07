"""Same-tool and cross-tool deduplication, set-based (project.md 3.7.3, ADR-0012).

Dedup runs *after* findings exist. It never changes status; it only sets ``duplicate_of`` to
point a newer finding at the oldest "original" sharing its key. Duplicates are excluded from
open-finding metrics. Everything here is one or two SQL statements — no per-row loop (#9).

Scope:
- Same-tool: same product (or engagement when ``deduplication_on_engagement``), same scanner,
  keyed on ``match_key``.
- Cross-tool: same product, any scanner, ``cross_tool_hash`` only (the scanner-independent
  CVE+component+version key, set only where those exist).

The original is the lowest ``id`` in a group (oldest insert). Re-running is safe: rows already
marked duplicate are excluded, so the surviving minimum stays the original.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def run_same_tool_dedup(
    session: Session, *, product_id: int, scanner_key: str, engagement_id: int | None = None
) -> int:
    """Point newer same-(product|engagement)+scanner findings at their oldest match_key twin.

    ``engagement_id`` set = the scanner's config has ``deduplication_on_engagement``; scope
    narrows to that engagement. Returns the number of findings newly marked duplicate.
    """
    scope_clause = "f.product_id = :product_id"
    params: dict[str, object] = {"product_id": product_id, "scanner_key": scanner_key}
    if engagement_id is not None:
        scope_clause = "f.engagement_id = :engagement_id"
        params["engagement_id"] = engagement_id

    stmt = text(
        f"""
        WITH ranked AS (
            SELECT f.id,
                   MIN(f.id) OVER (PARTITION BY f.match_key) AS original_id
              FROM core.finding f
              JOIN core.test t ON t.id = f.test_id
             WHERE {scope_clause}
               AND t.scanner_key = :scanner_key
               AND f.duplicate_of IS NULL
               AND f.match_key IS NOT NULL
        )
        UPDATE core.finding f
           SET duplicate_of = r.original_id, updated_at = now()
          FROM ranked r
         WHERE f.id = r.id
           AND r.original_id <> r.id
        RETURNING f.id
        """
    )
    return len(list(session.execute(stmt, params)))


def run_cross_tool_dedup(session: Session, *, product_id: int) -> int:
    """Point newer findings at the oldest cross_tool_hash twin across scanners in a product.

    Only findings carrying a ``cross_tool_hash`` participate (CVE+component present), so a
    SAST finding with no package never collides with another empty one. Returns the count
    newly marked duplicate.
    """
    stmt = text(
        """
        WITH ranked AS (
            SELECT f.id,
                   MIN(f.id) OVER (PARTITION BY f.cross_tool_hash) AS original_id
              FROM core.finding f
             WHERE f.product_id = :product_id
               AND f.duplicate_of IS NULL
               AND f.cross_tool_hash IS NOT NULL
        )
        UPDATE core.finding f
           SET duplicate_of = r.original_id, updated_at = now()
          FROM ranked r
         WHERE f.id = r.id
           AND r.original_id <> r.id
        RETURNING f.id
        """
    )
    return len(list(session.execute(stmt, {"product_id": product_id})))


def promote_duplicates_of(session: Session, *, original_id: int) -> int:
    """Promote the oldest remaining duplicate of a deleted original and repoint the rest.

    Call BEFORE deleting ``original_id``. The oldest duplicate becomes the new original
    (``duplicate_of = NULL``); every other duplicate of the old original is repointed to it.
    Returns the new original's id, or 0 if the finding had no duplicates.
    """
    new_original = session.execute(
        text(
            """
            SELECT MIN(id) FROM core.finding WHERE duplicate_of = :original_id
            """
        ),
        {"original_id": original_id},
    ).scalar_one_or_none()
    if new_original is None:
        return 0

    session.execute(
        text("UPDATE core.finding SET duplicate_of = NULL, updated_at = now() WHERE id = :nid"),
        {"nid": new_original},
    )
    session.execute(
        text(
            """
            UPDATE core.finding
               SET duplicate_of = :nid, updated_at = now()
             WHERE duplicate_of = :original_id AND id <> :nid
            """
        ),
        {"nid": new_original, "original_id": original_id},
    )
    return int(new_original)
