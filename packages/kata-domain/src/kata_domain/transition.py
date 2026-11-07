"""The single allowed path for changing a finding's status (project.md 3.8).

Rule (CLAUDE.md #6): every finding status change goes through ``transition()``. No other
code path may write ``finding.status`` directly. ``transition()`` validates the edge, keeps
``mitigated_at`` consistent with the status, and writes the audit row in the *caller's*
transaction (it never commits). SLA recompute (Phase 6) and the outbox event (Phase 7) hook
in here later.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import insert, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from .enums import ActorType, FindingStatus
from .models import AuditLog, Finding

S = FindingStatus

# Allowed status edges. Creation (-> active) is not a transition; it is an insert.
ALLOWED_TRANSITIONS: dict[FindingStatus, frozenset[FindingStatus]] = {
    S.ACTIVE: frozenset(
        {S.MITIGATED, S.FALSE_POSITIVE, S.OUT_OF_SCOPE, S.RISK_ACCEPTED, S.UNDER_REVIEW}
    ),
    S.MITIGATED: frozenset({S.ACTIVE}),
    S.FALSE_POSITIVE: frozenset({S.ACTIVE}),
    S.OUT_OF_SCOPE: frozenset({S.ACTIVE}),
    S.RISK_ACCEPTED: frozenset({S.ACTIVE}),
    S.UNDER_REVIEW: frozenset(
        {S.ACTIVE, S.MITIGATED, S.FALSE_POSITIVE, S.OUT_OF_SCOPE, S.RISK_ACCEPTED}
    ),
}


class InvalidTransition(ValueError):
    """Raised when a status edge is not permitted. Message is safe to show to users."""


class SupportsAdd(Protocol):
    """Structural type for the part of a SQLAlchemy Session that transition() uses."""

    def add(self, instance: object) -> None: ...


def is_allowed(from_status: FindingStatus, to_status: FindingStatus) -> bool:
    return to_status in ALLOWED_TRANSITIONS.get(from_status, frozenset())


def transition(
    session: SupportsAdd,
    finding: Finding,
    to_status: FindingStatus,
    *,
    actor_type: ActorType,
    actor_id: str,
    reason: str | None = None,
    now: datetime.datetime | None = None,
) -> AuditLog:
    """Move ``finding`` to ``to_status``, writing an audit row in the caller's transaction.

    Raises ``InvalidTransition`` if the edge is not permitted (including a no-op to the same
    status). Returns the ``AuditLog`` row that was added to the session.
    """
    from_status = finding.status
    if not is_allowed(from_status, to_status):
        raise InvalidTransition(
            f"Cannot transition finding from '{from_status.value}' to '{to_status.value}'."
        )

    moment = now or datetime.datetime.now(tz=datetime.UTC)
    finding.status = to_status
    finding.updated_at = moment

    # Keep mitigated_at consistent with the CHECK constraint
    # ((status = 'mitigated') = (mitigated_at IS NOT NULL)).
    if to_status is S.MITIGATED:
        finding.mitigated_at = moment
    elif from_status is S.MITIGATED:
        finding.mitigated_at = None

    audit = AuditLog(
        occurred_at=moment,
        actor_type=actor_type.value,
        actor_id=actor_id,
        entity="finding",
        entity_id=finding.id,
        action="status_changed",
        diff={
            "field": "status",
            "from": from_status.value,
            "to": to_status.value,
            "reason": reason,
        },
    )
    session.add(audit)
    # TODO(Phase 6): recompute SLA when status leaves/returns to 'active'.
    # TODO(Phase 7): write the finding.status_changed outbox row in this same transaction.
    return audit


def bulk_transition(
    session: Session,
    *,
    finding_ids: Sequence[int],
    from_status: FindingStatus,
    to_status: FindingStatus,
    actor_type: ActorType,
    actor_id: str,
    reason: str | None = None,
    now: datetime.datetime | None = None,
) -> list[int]:
    """Set-based status change for many findings (reimport reactivate/close). ADR-0012.

    The ONLY sanctioned bulk status path, alongside :func:`transition`. Performs one
    ``UPDATE ... WHERE id = ANY AND status = from_status`` (the status guard makes it
    idempotent and race-safe: a row already moved is skipped) and one set-based audit
    ``INSERT ... SELECT`` over exactly the rows that changed. Returns the changed ids.

    Raises :class:`InvalidTransition` if the single ``from → to`` edge is not permitted.
    """
    if not is_allowed(from_status, to_status):
        raise InvalidTransition(
            f"Cannot transition finding from '{from_status.value}' to '{to_status.value}'."
        )
    if not finding_ids:
        return []

    moment = now or datetime.datetime.now(tz=datetime.UTC)
    values: dict[str, object] = {"status": to_status, "updated_at": moment}
    # Keep mitigated_at consistent with the CHECK ((status='mitigated') = (mitigated_at NOT NULL)).
    if to_status is S.MITIGATED:
        values["mitigated_at"] = moment
    elif from_status is S.MITIGATED:
        values["mitigated_at"] = None

    changed = list(
        session.scalars(
            update(Finding)
            .where(Finding.id.in_(list(finding_ids)), Finding.status == from_status)
            .values(**values)
            .returning(Finding.id)
        ).all()
    )
    if not changed:
        return []

    diff = {
        "field": "status",
        "from": from_status.value,
        "to": to_status.value,
        "reason": reason,
    }
    session.execute(
        insert(AuditLog).from_select(
            ["occurred_at", "actor_type", "actor_id", "entity", "entity_id", "action", "diff"],
            select(
                literal(moment),
                literal(actor_type.value),
                literal(actor_id),
                literal("finding"),
                Finding.id,
                literal("status_changed"),
                literal(diff, type_=JSONB),
            ).where(Finding.id.in_(changed)),
        )
    )
    return changed
