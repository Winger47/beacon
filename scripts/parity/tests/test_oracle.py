"""Tests for the parity oracle (scripts/parity/scenario.py).

The oracle encodes the reimport contract (project.md 3.7.4) independently of kata_domain, so
these tests pin the expected create/untouched/reactivate/close counts the live harness checks
Kata (and DefectDojo) against.
"""

from __future__ import annotations

from scripts.parity.scenario import (
    Counts,
    Step,
    default_sequence,
    expected_counts,
)
from scripts.parity.trivy_report import Vuln, build_report


def test_default_sequence_counts() -> None:
    assert [c.as_tuple() for c in expected_counts(default_sequence())] == [
        (5, 0, 0, 0),  # v1 import: 5 created
        (2, 3, 0, 2),  # v2: 2 new, 3 kept, 2 closed
        (0, 5, 1, 0),  # v3: regression reactivates 1, nothing closes
        (0, 5, 0, 1),  # v4: do_not_reactivate keeps 1 closed, 1 new absence closes
    ]


def test_do_not_reactivate_leaves_mitigated_uncounted() -> None:
    v = Vuln("CVE-1", "pkg", "1.0")
    steps = [
        Step("import", "import", [v]),
        Step("close", "reimport", []),  # v absent -> mitigated
        Step("return-no-react", "reimport", [v], do_not_reactivate=True),
    ]
    counts = expected_counts(steps)
    assert counts[1] == Counts(closed=1)
    assert counts[2] == Counts()  # not reactivated, not untouched, not created


def test_close_old_findings_false_keeps_absent_active() -> None:
    a, b = Vuln("CVE-A", "pa", "1"), Vuln("CVE-B", "pb", "1")
    steps = [
        Step("import", "import", [a, b]),
        Step("partial-no-close", "reimport", [a], close_old_findings=False),
    ]
    counts = expected_counts(steps)
    assert counts[1] == Counts(untouched=1)  # b is NOT closed


def test_report_is_deterministic() -> None:
    vulns = [Vuln("CVE-2", "pkg", "1.0"), Vuln("CVE-1", "pkg", "2.0")]
    assert build_report(vulns) == build_report(vulns)


def test_report_is_valid_trivy_shape() -> None:
    import json

    data = json.loads(build_report([Vuln("CVE-9", "openssl", "3.0")]))
    assert data["SchemaVersion"] == 2
    vuln = data["Results"][0]["Vulnerabilities"][0]
    assert vuln["VulnerabilityID"] == "CVE-9"
    assert vuln["PkgName"] == "openssl"
