"""Golden-file test harness for parsers.

A golden test runs a parser over ``fixtures/<name>`` and compares the emitted findings
(one JSON object per line) to ``fixtures/<name>.expected.jsonl``. Run with
``pytest --update-golden`` to (re)generate the expected files.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from kata_parsers.base import ScannerParser

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Regenerate parser golden expected files instead of asserting.",
    )


def _render(parser: ScannerParser, fixture: Path) -> str:
    with fixture.open("rb") as fh:
        lines = [json.dumps(f.to_dict(), sort_keys=True) for f in parser.parse(fh)]
    return "\n".join(lines) + ("\n" if lines else "")


@pytest.fixture
def assert_golden(request: pytest.FixtureRequest) -> Callable[[ScannerParser, str], None]:
    update: bool = request.config.getoption("--update-golden")

    def _check(parser: ScannerParser, fixture_name: str) -> None:
        fixture = FIXTURES / fixture_name
        expected = FIXTURES / f"{fixture_name}.expected.jsonl"
        actual = _render(parser, fixture)
        if update:
            expected.write_text(actual)
            return
        assert expected.exists(), f"missing golden file {expected} (run --update-golden)"
        assert actual == expected.read_text()

    return _check
