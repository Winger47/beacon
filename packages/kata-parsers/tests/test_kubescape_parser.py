"""Golden + behaviour tests for the Kubescape parser.

Fixture is REAL Kubescape CLI v3.0.44 output (`kubescape scan --format json` over a
deliberately bad Deployment), trimmed to 3 failed controls + 1 passing. Regenerate with a newer
Kubescape and `pytest --update-golden` when bumping versions.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

from kata_parsers import get_parser
from kata_parsers.base import Finding, ParserError, ScannerParser, Severity
from kata_parsers.kubescape import KubescapeParser

FIXTURES = Path(__file__).parent / "fixtures"
RESOURCE_ID = "path=2239022173/api=apps/v1/default/Deployment/nginx"


def _parse_fixture() -> list[Finding]:
    with (FIXTURES / "kubescape_sample.json").open("rb") as fh:
        return list(KubescapeParser().parse(fh))


def test_registry_resolves_kubescape() -> None:
    assert isinstance(get_parser("kubescape"), KubescapeParser)


def test_kubescape_sniff() -> None:
    assert KubescapeParser().sniff(b'{"summaryDetails": {"controls": {}}, "results": []}')
    assert not KubescapeParser().sniff(b'{"SchemaVersion": 2, "Results": []}')


def test_kubescape_golden(assert_golden: Callable[[ScannerParser, str], None]) -> None:
    assert_golden(KubescapeParser(), "kubescape_sample.json")


def test_one_finding_per_failed_control_on_the_resource() -> None:
    """The think-first decision: one finding per failed (control, resource) pair."""
    findings = _parse_fixture()
    assert len(findings) == 3  # 3 failed controls on the single resource (1 passing dropped)
    assert {f.vuln_id_from_tool for f in findings} == {"C-0271", "C-0211", "C-0269"}
    assert all(f.locations[0] == {"kind": "k8s", "resource_id": RESOURCE_ID} for f in findings)


def test_passing_controls_are_skipped() -> None:
    assert all(f.vuln_id_from_tool != "C-0296" for f in _parse_fixture())


def test_severity_joined_from_summary_details() -> None:
    """scoreFactor lives only in summaryDetails; the parser must join it to the result."""
    by_control = {f.vuln_id_from_tool: f for f in _parse_fixture()}
    assert by_control["C-0271"].severity is Severity.HIGH  # scoreFactor 8
    assert by_control["C-0269"].severity is Severity.LOW  # scoreFactor 3


# --- unit tests for branches the real fixture doesn't exercise ----------------
def test_missing_score_factor_defaults_to_info() -> None:
    report = b"""
    {"summaryDetails": {"controls": {}},
     "results": [{"resourceID": "r", "controls": [
        {"controlID": "C-9999", "name": "no score", "status": {"status": "failed"}}]}]}
    """
    (finding,) = KubescapeParser().parse(io.BytesIO(report))
    assert finding.severity is Severity.INFO
    assert finding.extra["severity_source"] == "defaulted-info-no-scoreFactor"


def test_malformed_kubescape_raises_parser_error() -> None:
    import pytest

    with pytest.raises(ParserError):
        list(KubescapeParser().parse(io.BytesIO(b'{"results": [ broken')))
