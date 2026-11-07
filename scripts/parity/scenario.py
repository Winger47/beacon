"""The parity fixture *sequence* and its backend-independent oracle.

The oracle replays the sequence against a plain in-memory model of the reimport contract
(project.md 3.7.4) and emits the create / untouched / reactivate / close counts each step must
produce. It depends on nothing in ``kata_domain`` — that is the point: it is an independent
second opinion that a backend's own counts are checked against, so an implementation bug
cannot also corrupt the expectation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .trivy_report import Vuln

_ACTIVE = "active"
_MITIGATED = "mitigated"


@dataclass(frozen=True, slots=True)
class Step:
    """One import or reimport in the sequence."""

    label: str
    kind: str  # "import" | "reimport"
    vulns: list[Vuln]
    close_old_findings: bool = True
    do_not_reactivate: bool = False


@dataclass(frozen=True, slots=True)
class Counts:
    """The four reimport outcomes. ``import`` steps report only ``created``."""

    created: int = 0
    untouched: int = 0
    reactivated: int = 0
    closed: int = 0

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.created, self.untouched, self.reactivated, self.closed)


@dataclass
class _Model:
    """Mutable per-key status map the oracle walks the sequence with."""

    status: dict[tuple[str, str, str], str] = field(default_factory=dict)

    def apply(self, step: Step) -> Counts:
        incoming = {v.key for v in step.vulns}
        if step.kind == "import":
            created = 0
            for k in incoming:
                if k not in self.status:
                    self.status[k] = _ACTIVE
                    created += 1
            return Counts(created=created)

        existing = self.status
        active = {k for k, s in existing.items() if s == _ACTIVE}
        mitigated = {k for k, s in existing.items() if s == _MITIGATED}

        created = untouched = reactivated = closed = 0
        for k in incoming:
            if k not in existing:
                existing[k] = _ACTIVE
                created += 1
            elif k in active:
                untouched += 1
            elif k in mitigated:
                if step.do_not_reactivate:
                    continue  # platform wins: stays mitigated, counted nowhere
                existing[k] = _ACTIVE
                reactivated += 1

        if step.close_old_findings:
            for k in active - incoming:
                existing[k] = _MITIGATED
                closed += 1
        return Counts(
            created=created, untouched=untouched, reactivated=reactivated, closed=closed
        )


def expected_counts(steps: list[Step]) -> list[Counts]:
    """Oracle: the counts each step must produce, computed independently of any backend."""
    model = _Model()
    return [model.apply(step) for step in steps]


def _v(cve: str) -> Vuln:
    # One stable (pkg, version) per CVE so the dedup key is the CVE id alone.
    return Vuln(cve=cve, pkg=f"pkg-{cve[-4:]}", version="1.0.0")


A, B, C, D, E, F, G = (_v(c) for c in ("CVE-0001", "CVE-0002", "CVE-0003", "CVE-0004",
                                       "CVE-0005", "CVE-0006", "CVE-0007"))


def default_sequence() -> list[Step]:
    """Exercises all four outcomes plus ``do_not_reactivate`` (project.md Phase 3 Week 3).

    Kept below the mass-closure breaker floor (``min_findings``) on purpose so no step pauses;
    the breaker's pause path is covered by unit tests and documented as a DefectDojo divergence.
    """
    return [
        Step("v1 import 5", "import", [A, B, C, D, E]),
        # 3 kept (A,B,C) + 2 new (F,G); D,E vanish -> close.
        Step("v2 reimport 3+2, close D,E", "reimport", [A, B, C, F, G]),
        # D regresses (was mitigated) -> reactivate; E stays closed (absent, already mitigated).
        Step("v3 reimport, D regression", "reimport", [A, B, C, F, G, D]),
        # E reappears but do_not_reactivate -> stays closed; D now absent -> closes.
        Step(
            "v4 reimport, do_not_reactivate",
            "reimport",
            [A, B, C, F, G, E],
            do_not_reactivate=True,
        ),
    ]


def with_scanner(steps: list[Step], _scanner: str) -> list[Step]:
    """Hook for future per-scanner sequences; identity for now (Trivy only)."""
    return [replace(s) for s in steps]
