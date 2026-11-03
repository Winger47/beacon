"""Unit tests for transition(): every allowed and forbidden status edge (project.md 3.8)."""

from __future__ import annotations

import datetime

import pytest

from kata_domain.enums import ActorType, FindingStatus
from kata_domain.models import AuditLog, Finding
from kata_domain.transition import (
    ALLOWED_TRANSITIONS,
    InvalidTransition,
    is_allowed,
    transition,
)

S = FindingStatus
FIXED_NOW = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=datetime.UTC)


class FakeSession:
    """Collects objects passed to add(), standing in for a SQLAlchemy Session."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)


def make_finding(
    status: FindingStatus, *, mitigated_at: datetime.datetime | None = None
) -> Finding:
    f = Finding(id=1, test_id=1, engagement_id=1, product_id=1, title="x", status=status)
    f.mitigated_at = mitigated_at
    return f


def _all_pairs() -> list[tuple[FindingStatus, FindingStatus]]:
    return [(a, b) for a in FindingStatus for b in FindingStatus]


@pytest.mark.parametrize(("frm", "to"), _all_pairs())
def test_is_allowed_matches_table(frm: FindingStatus, to: FindingStatus) -> None:
    expected = to in ALLOWED_TRANSITIONS.get(frm, frozenset())
    assert is_allowed(frm, to) is expected


@pytest.mark.parametrize(
    ("frm", "to"),
    [(frm, to) for frm, tos in ALLOWED_TRANSITIONS.items() for to in tos],
)
def test_allowed_edges_apply(frm: FindingStatus, to: FindingStatus) -> None:
    session = FakeSession()
    finding = make_finding(frm, mitigated_at=FIXED_NOW if frm is S.MITIGATED else None)

    audit = transition(
        session,
        finding,
        to,
        actor_type=ActorType.USER,
        actor_id="42",
        reason="because",
        now=FIXED_NOW,
    )

    assert finding.status is to
    assert finding.updated_at == FIXED_NOW
    # mitigated_at tracks the 'mitigated' status exactly.
    if to is S.MITIGATED:
        assert finding.mitigated_at == FIXED_NOW
    elif frm is S.MITIGATED:
        assert finding.mitigated_at is None
    assert isinstance(audit, AuditLog)
    assert session.added == [audit]
    assert audit.action == "status_changed"
    assert audit.actor_type == "user"
    assert audit.actor_id == "42"
    assert audit.entity == "finding"
    assert audit.entity_id == 1
    assert audit.diff == {"field": "status", "from": frm.value, "to": to.value, "reason": "because"}


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (frm, to)
        for frm, to in _all_pairs()
        if to not in ALLOWED_TRANSITIONS.get(frm, frozenset())
    ],
)
def test_forbidden_edges_raise(frm: FindingStatus, to: FindingStatus) -> None:
    session = FakeSession()
    finding = make_finding(frm, mitigated_at=FIXED_NOW if frm is S.MITIGATED else None)

    with pytest.raises(InvalidTransition):
        transition(session, finding, to, actor_type=ActorType.USER, actor_id="42")

    # No mutation and no audit row on a rejected transition.
    assert finding.status is frm
    assert session.added == []


def test_same_status_is_rejected() -> None:
    session = FakeSession()
    finding = make_finding(S.ACTIVE)
    with pytest.raises(InvalidTransition):
        transition(session, finding, S.ACTIVE, actor_type=ActorType.SYSTEM, actor_id="sys")


def test_reactivate_clears_mitigated_at() -> None:
    session = FakeSession()
    finding = make_finding(S.MITIGATED, mitigated_at=FIXED_NOW)
    transition(
        session, finding, S.ACTIVE, actor_type=ActorType.IMPORT, actor_id="job-1", now=FIXED_NOW
    )
    assert finding.status is S.ACTIVE
    assert finding.mitigated_at is None
