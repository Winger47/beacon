"""Phase 0 smoke test for the parser SDK package. Real golden-file tests arrive in Phase 2."""

from __future__ import annotations

import kata_parsers


def test_package_imports_and_has_version() -> None:
    assert isinstance(kata_parsers.__version__, str)
    assert kata_parsers.__version__
