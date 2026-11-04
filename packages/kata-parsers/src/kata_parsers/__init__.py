"""Kata parser SDK.

Base classes, registry and limits for streaming scanner parsers (project.md 3.4).
Importing this package registers the built-in parsers.
"""

from __future__ import annotations

# Import parser modules for their @register side effect.
from . import generic as _generic  # noqa: F401
from . import kubescape as _kubescape  # noqa: F401
from . import trivy as _trivy  # noqa: F401
from .base import Finding, ParserError, ParserLimits, ScannerParser, Severity
from .generic import generic_schema
from .registry import get_parser, register, registered_keys

__version__ = "0.0.0"

__all__ = [
    "Finding",
    "ParserError",
    "ParserLimits",
    "ScannerParser",
    "Severity",
    "__version__",
    "generic_schema",
    "get_parser",
    "register",
    "registered_keys",
]
