"""Golden + behaviour tests for the Trivy parser.

Implemented at the user's direction (CLAUDE.md "You build" split was waived for trivy.py).
The fixture is schema-faithful but hand-authored; regenerate from a real Trivy run and
re-run `pytest --update-golden` before relying on it.
"""

from __future__ import annotations

import io
from collections.abc import Callable

from kata_parsers import get_parser
from kata_parsers.base import ParserError, ScannerParser
from kata_parsers.trivy import TrivyParser


def test_registry_resolves_trivy() -> None:
    assert isinstance(get_parser("trivy"), TrivyParser)


def test_trivy_sniff() -> None:
    assert TrivyParser().sniff(b'{"SchemaVersion": 2, "Results": []}')
    assert not TrivyParser().sniff(b'{"findings": []}')


def test_trivy_golden(assert_golden: Callable[[ScannerParser, str], None]) -> None:
    assert_golden(TrivyParser(), "trivy_sample.json")


def _parse_fixture() -> list[object]:
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "trivy_sample.json"
    with fixture.open("rb") as fh:
        return list(TrivyParser().parse(fh))


def test_each_vuln_carries_its_target_image() -> None:
    """Target is attached to every vulnerability in its Result (the ordering assumption)."""
    findings = _parse_fixture()
    vulns = [f for f in findings if f.locations and f.locations[0]["kind"] == "image"]  # type: ignore[index]
    assert vulns, "expected image-located vulnerabilities"
    assert all(
        f.locations[0]["image"] == "alpine:3.19 (alpine 3.19.1)" for f in vulns  # type: ignore[index]
    )


def test_passing_misconfigurations_are_skipped() -> None:
    """Only Status == FAIL misconfigurations become findings; PASS is dropped."""
    findings = _parse_fixture()
    titles = {f.title for f in findings}  # type: ignore[attr-defined]
    assert "AVD-DS-0002 Image user should not be 'root'" in titles
    assert not any("DS-0026" in t or "HEALTHCHECK" in t for t in titles)


def test_no_fixed_version_mitigation() -> None:
    findings = _parse_fixture()
    busybox = next(f for f in findings if f.component_name == "busybox")  # type: ignore[attr-defined]
    assert busybox.mitigation == "No fixed version available"  # type: ignore[attr-defined]


def test_malformed_trivy_raises_parser_error() -> None:
    import pytest

    with pytest.raises(ParserError):
        list(TrivyParser().parse(io.BytesIO(b'{"SchemaVersion": 2, "Results": [ broken')))
