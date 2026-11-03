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


class Role(StrEnum):
    """RBAC roles, lowest to highest privilege (project.md 2.8).

    Used for global roles, product-type memberships and product memberships. Stored as
    text with a CHECK constraint (not a PG enum) so the role set can evolve without an
    enum migration. See ADR-0005.
    """

    READER = "reader"
    API_IMPORTER = "api_importer"
    WRITER = "writer"
    MAINTAINER = "maintainer"
    OWNER = "owner"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]

    def satisfies(self, required: Role) -> bool:
        """True if this role is at least as privileged as ``required``.

        API_IMPORTER is a special case: it can import but is not a general Reader+. It
        only satisfies itself; comparisons for read/write use the linear ranks below.
        """
        if self is Role.API_IMPORTER or required is Role.API_IMPORTER:
            return self is required
        return self.rank >= required.rank


# Linear privilege order for read/write checks. API_IMPORTER sits outside this ladder
# (it is a narrow CI capability), so it is given a low rank and gated by satisfies().
_ROLE_RANK: dict[Role, int] = {
    Role.API_IMPORTER: 0,
    Role.READER: 1,
    Role.WRITER: 2,
    Role.MAINTAINER: 3,
    Role.OWNER: 4,
}
