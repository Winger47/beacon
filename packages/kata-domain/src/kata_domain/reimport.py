"""Set-based reimport diff, finalization and the mass-closure breaker (3.7.4, ADR-0013).

Reimport compares an incoming report against a Test's existing findings and produces four
outcomes per item: **create / untouched / reactivate / close**. The whole diff is pushed into
PostgreSQL via the ``ingest.reimport_seen`` staging table so it scales to millions of rows
without holding a Python dict of every existing finding (3.7.4). Status changes go through
``bulk_transition`` (ADR-0012); human-triaged statuses are never auto-closed.

Think-first answers (project.md 3.7.4):
 1. A key repeated across batches is idempotent: ``reimport_seen`` has a PK on
    (job_id, match_key) with ON CONFLICT DO NOTHING, and CREATE inserts only keys with no
    existing finding in the Test, so the same key seen twice creates one finding.
 2. A human-triaged finding (false_positive/out_of_scope/risk_accepted) absent from a report
    is NOT closed — step 7 touches only ``status='active'``. The human decision wins.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import dedup
from .enums import ActorType, FindingStatus
from .models import Finding, ReimportDecision, Test, TestImport
from .transition import bulk_transition


@dataclass(frozen=True, slots=True)
class IncomingFinding:
    """One parsed finding ready for reimport: its match key and the row to insert on CREATE."""

    match_key: str
    finding: Finding


@dataclass(frozen=True, slots=True)
class BreakerConfig:
    """Mass-closure circuit breaker thresholds (ADR-0013)."""

    close_ratio: float = 0.50
    prev_ratio: float = 0.50
    min_findings: int = 10


@dataclass(frozen=True, slots=True)
class ReimportOutcome:
    status: str  # "completed" | "needs_confirmation"
    import_job_id: str
    created: int
    reactivated: int
    untouched: int
    closed: int
    close_candidates: int = 0


def should_pause(
    *, active_before: int, to_close: int, incoming_count: int, cfg: BreakerConfig
) -> bool:
    """True when auto-closing would be dangerous: a big close from a suspiciously small report.

    Both conditions must hold, and the Test must be above a floor so tiny Tests never trip.
    """
    if active_before < cfg.min_findings:
        return False
    closes_a_lot = to_close > cfg.close_ratio * active_before
    report_shrank = incoming_count < cfg.prev_ratio * active_before
    return closes_a_lot and report_shrank


def _seen_subquery() -> str:
    return "SELECT match_key FROM ingest.reimport_seen WHERE job_id = :job_id"


def reimport(
    session: Session,
    *,
    test: Test,
    incoming: Sequence[IncomingFinding],
    job_id: str,
    actor_id: str,
    close_old_findings: bool = True,
    do_not_reactivate: bool = False,
    breaker: BreakerConfig | None = None,
) -> ReimportOutcome:
    """Diff ``incoming`` against ``test``'s findings and apply create/untouched/reactivate/close.

    Returns a :class:`ReimportOutcome`. If the mass-closure breaker trips, nothing is closed,
    a :class:`ReimportDecision` is persisted and status is ``needs_confirmation`` (resolve with
    :func:`confirm_reimport` / :func:`reject_reimport`).
    """
    cfg = breaker or BreakerConfig()
    test_id = test.id

    # Snapshot the active count BEFORE any mutation: this is the breaker's "size of what was
    # there", so creates/reactivations later in this job don't inflate it.
    active_before = count_active(session, test_id)

    # 1. Stage incoming keys (dedupes within the report via the PK). Keep first row per key
    #    for CREATE.
    by_key: dict[str, Finding] = {}
    for item in incoming:
        by_key.setdefault(item.match_key, item.finding)
    if by_key:
        session.execute(
            text(
                "INSERT INTO ingest.reimport_seen (job_id, match_key) "
                "VALUES (:job_id, :match_key) ON CONFLICT DO NOTHING"
            ),
            [{"job_id": job_id, "match_key": k} for k in by_key],
        )
    incoming_count = len(by_key)

    # 2. UNTOUCHED: matched findings that are active or human-triaged keep their status; only
    #    last_seen_at advances. (Mitigated matches are handled as REACTIVATE below.)
    untouched = len(
        list(
            session.execute(
                text(
                    f"""
                    UPDATE core.finding
                       SET last_seen_at = now()
                     WHERE test_id = :test_id
                       AND status <> 'mitigated'
                       AND match_key IN ({_seen_subquery()})
                    RETURNING id
                    """
                ),
                {"test_id": test_id, "job_id": job_id},
            )
        )
    )

    # 3. REACTIVATE: previously mitigated findings whose key reappears.
    reactivated = 0
    reactivate_ids = list(
        session.scalars(
            text(
                f"""
                SELECT id FROM core.finding
                 WHERE test_id = :test_id AND status = 'mitigated'
                   AND match_key IN ({_seen_subquery()})
                """
            ),
            {"test_id": test_id, "job_id": job_id},
        ).all()
    )
    if reactivate_ids and not do_not_reactivate:
        changed = bulk_transition(
            session,
            finding_ids=reactivate_ids,
            from_status=FindingStatus.MITIGATED,
            to_status=FindingStatus.ACTIVE,
            actor_type=ActorType.IMPORT,
            actor_id=actor_id,
            reason=f"reappeared in reimport job {job_id}",
        )
        reactivated = len(changed)
        if changed:
            session.execute(
                text(
                    "UPDATE core.finding SET last_seen_at = now() WHERE id = ANY(:ids)"
                ),
                {"ids": changed},
            )
    # do_not_reactivate: leave them mitigated (platform is source of truth) — counted neither
    # untouched nor reactivated; they simply stay closed.

    # 4. CREATE: incoming keys with no existing finding in this Test.
    new_keys = set(
        session.scalars(
            text(
                """
                SELECT s.match_key
                  FROM ingest.reimport_seen s
                 WHERE s.job_id = :job_id
                   AND NOT EXISTS (
                         SELECT 1 FROM core.finding f
                          WHERE f.test_id = :test_id AND f.match_key = s.match_key
                   )
                """
            ),
            {"test_id": test_id, "job_id": job_id},
        ).all()
    )
    created = 0
    for key in new_keys:
        session.add(by_key[key])
        created += 1
    if created:
        session.flush()
        dedup.run_same_tool_dedup(
            session, product_id=test.engagement.product_id, scanner_key=test.scanner_key
        )
        dedup.run_cross_tool_dedup(session, product_id=test.engagement.product_id)

    # 5. FINALIZE. Serialize closers for this Test (3.7.4 step 6).
    session.execute(
        text("SELECT pg_advisory_xact_lock(:test_id)"), {"test_id": test_id}
    )
    closed = 0
    close_candidates = 0
    status = "completed"
    if close_old_findings:
        candidate_ids = list(
            session.scalars(
                text(
                    f"""
                    SELECT id FROM core.finding
                     WHERE test_id = :test_id AND status = 'active'
                       AND match_key IS NOT NULL
                       AND match_key NOT IN ({_seen_subquery()})
                    """
                ),
                {"test_id": test_id, "job_id": job_id},
            ).all()
        )
        close_candidates = len(candidate_ids)
        if candidate_ids and should_pause(
            active_before=active_before,
            to_close=close_candidates,
            incoming_count=incoming_count,
            cfg=cfg,
        ):
            session.add(
                ReimportDecision(
                    import_job_id=job_id,
                    test_id=test_id,
                    status="needs_confirmation",
                    close_candidate_ids=candidate_ids,
                    active_before=active_before,
                    incoming_count=incoming_count,
                    previous_import_count=active_before,
                )
            )
            status = "needs_confirmation"
        elif candidate_ids:
            closed = len(
                bulk_transition(
                    session,
                    finding_ids=candidate_ids,
                    from_status=FindingStatus.ACTIVE,
                    to_status=FindingStatus.MITIGATED,
                    actor_type=ActorType.IMPORT,
                    actor_id=actor_id,
                    reason=f"absent from reimport job {job_id} (close_old_findings)",
                )
            )

    # 6. Record history and clean up the job's staging rows.
    session.add(
        TestImport(
            test_id=test_id,
            import_job_id=job_id,
            kind="reimport",
            created_count=created,
            untouched_count=untouched,
            reactivated_count=reactivated,
            closed_count=closed,
        )
    )
    session.execute(
        text("DELETE FROM ingest.reimport_seen WHERE job_id = :job_id"), {"job_id": job_id}
    )
    session.flush()
    return ReimportOutcome(
        status=status,
        import_job_id=job_id,
        created=created,
        reactivated=reactivated,
        untouched=untouched,
        closed=closed,
        close_candidates=close_candidates,
    )


def count_active(session: Session, test_id: int) -> int:
    """Count of currently-active findings in a Test (used for the breaker's active_before)."""
    return int(
        session.execute(
            text(
                "SELECT count(*) FROM core.finding "
                "WHERE test_id = :test_id AND status = 'active'"
            ),
            {"test_id": test_id},
        ).scalar_one()
    )


def confirm_reimport(session: Session, *, decision: ReimportDecision, actor_id: str) -> int:
    """Apply a paused close set after human confirmation. Returns the number closed."""
    if decision.status != "needs_confirmation":
        return 0
    closed = len(
        bulk_transition(
            session,
            finding_ids=decision.close_candidate_ids,
            from_status=FindingStatus.ACTIVE,
            to_status=FindingStatus.MITIGATED,
            actor_type=ActorType.IMPORT,
            actor_id=actor_id,
            reason=f"confirmed mass closure for reimport job {decision.import_job_id}",
        )
    )
    session.execute(
        text(
            "UPDATE core.test_import SET closed_count = :closed "
            "WHERE import_job_id = :job_id AND kind = 'reimport'"
        ),
        {"closed": closed, "job_id": decision.import_job_id},
    )
    decision.status = "confirmed"
    session.execute(
        text(
            "UPDATE core.reimport_decision SET resolved_at = now() "
            "WHERE import_job_id = :job_id"
        ),
        {"job_id": decision.import_job_id},
    )
    session.flush()
    return closed


def reject_reimport(session: Session, *, decision: ReimportDecision) -> None:
    """Discard a paused close set: nothing closes, the active findings stay active."""
    if decision.status != "needs_confirmation":
        return
    decision.status = "rejected"
    session.execute(
        text(
            "UPDATE core.reimport_decision SET resolved_at = now() "
            "WHERE import_job_id = :job_id"
        ),
        {"job_id": decision.import_job_id},
    )
    session.flush()
