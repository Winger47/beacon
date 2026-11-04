"""Golden + behaviour tests for the Trivy parser.

Fixtures are REAL Trivy v0.58 output (trimmed): ``trivy_sample.json`` is
``trivy image --format json alpine:3.19`` cut to 4 vulnerabilities; ``trivy_config_sample.json``
is ``trivy config --format json`` over a deliberately bad Dockerfile. Regenerate with a newer
Trivy and `pytest --update-golden` when bumping versions.

Implemented by Claude at the user's direction (the CLAUDE.md "You build" split for trivy.py
was waived).
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

from kata_parsers import get_parser
from kata_parsers.base import Finding, ParserError, ScannerParser
from kata_parsers.trivy import TrivyParser

FIXTURES = Path(__file__).parent / "fixtures"


def _parse(name: str) -> list[Finding]:
    with (FIXTURES / name).open("rb") as fh:
        return list(TrivyParser().parse(fh))


def test_registry_resolves_trivy() -> None:
    assert isinstance(get_parser("trivy"), TrivyParser)


def test_trivy_sniff() -> None:
    assert TrivyParser().sniff(b'{"SchemaVersion": 2, "Results": []}')
    assert not TrivyParser().sniff(b'{"findings": []}')


def test_trivy_image_golden(assert_golden: Callable[[ScannerParser, str], None]) -> None:
    assert_golden(TrivyParser(), "trivy_sample.json")


def test_trivy_config_golden(assert_golden: Callable[[ScannerParser, str], None]) -> None:
    assert_golden(TrivyParser(), "trivy_config_sample.json")


def test_each_vuln_carries_its_target_image() -> None:
    """Every vulnerability is located at its Result's Target image."""
    findings = _parse("trivy_sample.json")
    assert findings, "expected real vulnerabilities in the fixture"
    assert all(f.locations[0]["kind"] == "image" for f in findings)
    assert all(f.locations[0]["image"] == "alpine:3.19 (alpine 3.19.9)" for f in findings)


def test_same_cve_across_packages_stays_separate() -> None:
    """Faithfulness: one CVE in several packages is several findings (dedup decides later)."""
    findings = _parse("trivy_sample.json")
    dupes = [f for f in findings if f.vuln_id_from_tool == "CVE-2024-58251"]
    assert len(dupes) == 2  # busybox and busybox-binsh in the trimmed fixture
    assert {f.component_name for f in dupes} == {"busybox", "busybox-binsh"}


def test_misconfigurations_map_to_file_locations() -> None:
    findings = _parse("trivy_config_sample.json")
    assert findings, "expected real misconfigurations"
    assert all(f.locations[0]["kind"] == "file" for f in findings)
    assert all(f.locations[0]["path"] == "Dockerfile" for f in findings)
    assert any("Image user should not be 'root'" in f.title for f in findings)


# --- unit tests for branches the real fixtures don't exercise -----------------
def test_no_fixed_version_mitigation() -> None:
    report = b"""
    {"SchemaVersion": 2, "Results": [{"Target": "img", "Vulnerabilities": [
        {"VulnerabilityID": "CVE-X", "PkgName": "p", "InstalledVersion": "1",
         "Severity": "LOW"}]}]}
    """
    (finding,) = TrivyParser().parse(io.BytesIO(report))
    assert finding.mitigation == "No fixed version available"


def test_passing_misconfiguration_is_skipped() -> None:
    report = b"""
    {"SchemaVersion": 2, "Results": [{"Target": "Dockerfile", "Misconfigurations": [
        {"ID": "DS001", "Title": "ok", "Severity": "LOW", "Status": "PASS"},
        {"ID": "DS002", "Title": "bad", "Severity": "HIGH", "Status": "FAIL"}]}]}
    """
    findings = list(TrivyParser().parse(io.BytesIO(report)))
    assert [f.vuln_id_from_tool for f in findings] == ["DS002"]


def test_malformed_trivy_raises_parser_error() -> None:
    import pytest

    with pytest.raises(ParserError):
        list(TrivyParser().parse(io.BytesIO(b'{"SchemaVersion": 2, "Results": [ broken')))
