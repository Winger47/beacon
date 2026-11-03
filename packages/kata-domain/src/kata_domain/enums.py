"""Domain enumerations.

These mirror the PostgreSQL enum types created in the `core` schema migration
(``core.severity``, ``core.finding_status``). The migration owns the DB types; these
Python enums carry the same string labels for use in the ORM and services.
"""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    """Finding severity. Labels match ``core.severity``."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(StrEnum):
    """Finding lifecycle status. Labels match ``core.finding_status``.

    Kata deliberately uses a single status enum (plus a ``verified`` flag and a
    ``duplicate_of`` reference) instead of DefectDojo's independent booleans, so that
    invalid state combinations become unrepresentable. See ADR-0002.
    """

    ACTIVE = "active"
    MITIGATED = "mitigated"
    FALSE_POSITIVE = "false_positive"
    OUT_OF_SCOPE = "out_of_scope"
    RISK_ACCEPTED = "risk_accepted"
    UNDER_REVIEW = "under_review"


class ActorType(StrEnum):
    """Who caused an audited change. Matches ``core.audit_log.actor_type``."""

    USER = "user"
    SYSTEM = "system"
    IMPORT = "import"
