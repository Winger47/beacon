"""Golden + behaviour tests for the Kata Generic JSON parser."""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest

from kata_parsers import get_parser
from kata_parsers.base import ParserError, ScannerParser, Severity
from kata_parsers.generic import GenericJsonParser


def test_generic_golden(assert_golden: Callable[[ScannerParser, str], None]) -> None:
    assert_golden(GenericJsonParser(), "generic_sample.json")


def test_registry_resolves_generic() -> None:
    assert isinstance(get_parser("generic"), GenericJsonParser)


def test_unsupported_scanner_raises() -> None:
    with pytest.raises(ParserError):
        get_parser("does-not-exist")


def test_missing_title_raises() -> None:
    data = b'{"findings": [{"severity": "high"}]}'
    with pytest.raises(ParserError):
        list(GenericJsonParser().parse(io.BytesIO(data)))


def test_severity_normalization() -> None:
    assert Severity.from_text("Critical") is Severity.CRITICAL
    assert Severity.from_text("moderate") is Severity.MEDIUM
    assert Severity.from_text(None) is Severity.INFO
    assert Severity.from_text("bogus") is Severity.INFO


def test_sniff_detects_generic() -> None:
    assert GenericJsonParser().sniff(b'{"schema":"kata-generic-v1","findings":[]}')
