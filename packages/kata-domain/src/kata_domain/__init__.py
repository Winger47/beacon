"""Kata domain package.

Home of the domain model, repository layer, the single ``transition()`` service for
finding status changes, and (behind the "You build" rule) hashing, dedup and reimport logic.

Phase 1: core schema models, enums and the declarative base.
"""

from __future__ import annotations

from .db import CORE_SCHEMA, Base
from .enums import ActorType, FindingStatus, Severity

__version__ = "0.0.0"

__all__ = [
    "CORE_SCHEMA",
    "ActorType",
    "Base",
    "FindingStatus",
    "Severity",
    "__version__",
]
