"""Golden + behaviour tests for the Kubescape parser.

Fixture is schema-faithful but hand-authored (see kubescape.py's validation caveat);
regenerate from a real `kubescape scan --format json` run before relying on it.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

from kata_parsers import get_parser
from kata_parsers.base import ParserError, ScannerParser, Severity
from kata_parsers.kubescape import KubescapeParser


def test_registry_resolves_kubescape() -> None:
    assert isinstance(get_parser("kubescape"), KubescapeParser)


def test_kubescape_sniff() -> None:
    assert KubescapeParser().sniff(b'{"summaryDetails": {"controls": {}}, "results": []}')
    assert not KubescapeParser().sniff(b'{"SchemaVersion": 2, "Results": []}')


def test_kubescape_golden(assert_golden: Callable[[ScannerParser, str], None]) -> None:
    assert_golden(KubescapeParser(), "kubescape_sample.json")


def _parse_fixture() -> list[object]:
    fixture = Path(__file__).parent / "fixtures" / "kubescape_sample.json"
    with fixture.open("rb") as fh:
        return list(KubescapeParser().parse(fh))


def test_one_finding_per_failed_control_per_resource() -> None:
    """The think-first decision: a control failing on N resources is N findings."""
    findings = _parse_fixture()
    # C-0016 fails on nginx AND kube-proxy (2), C-0017 fails on nginx (1); C-0034 passes (0).
    assert len(findings) == 3
    pairs = {(f.vuln_id_from_tool, f.locations[0]["resource_id"]) for f in findings}  # type: ignore[attr-defined,index]
    assert pairs == {
        ("C-0016", "apps/v1/default/Deployment/nginx"),
        ("C-0017", "apps/v1/default/Deployment/nginx"),
        ("C-0016", "apps/v1/kube-system/DaemonSet/kube-proxy"),
    }


def test_passing_controls_are_skipped() -> None:
    findings = _parse_fixture()
    assert all(f.vuln_id_from_tool != "C-0034" for f in findings)  # type: ignore[attr-defined]


def test_severity_from_score_factor() -> None:
    findings = _parse_fixture()
    by_control = {f.vuln_id_from_tool: f for f in findings}  # type: ignore[attr-defined]
    assert by_control["C-0016"].severity is Severity.HIGH  # scoreFactor 7.0
    assert by_control["C-0017"].severity is Severity.MEDIUM  # scoreFactor 5.0


def test_malformed_kubescape_raises_parser_error() -> None:
    import pytest

    with pytest.raises(ParserError):
        list(KubescapeParser().parse(io.BytesIO(b'{"results": [ broken')))
