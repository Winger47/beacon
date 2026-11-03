"""Phase 0 smoke test: the package imports and exposes a version.

Exists so the Python toolchain (pytest/ruff/mypy) is exercised end-to-end from day one.
Real domain tests arrive in Phase 1.
"""

from __future__ import annotations

import kata_domain


def test_package_imports_and_has_version() -> None:
    assert isinstance(kata_domain.__version__, str)
    assert kata_domain.__version__
