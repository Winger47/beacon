"""SQLAlchemy ORM models for the Kata `core` schema (Phase 1 Week 1 subset).

The migration in ``services/core-api/migrations`` is the DDL source of truth; these models
mirror it exactly (columns, enum types, check constraints, and the hot-path indexes from
project.md 3.2) so future Alembic autogenerate stays consistent.

Scope: the tables enumerated for Phase 1 Week 1. Endpoints, risk acceptance and the outbox
are intentionally deferred to their own phases (6 and 7).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .enums import FindingStatus, Severity

# PostgreSQL enum types. create_type=False: the migration owns CREATE TYPE.
# values_callable makes SQLAlchemy persist the *values* (lowercase labels), not member names.
SEVERITY_ENUM = ENUM(
    Severity,
    name="severity",
    schema="core",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)
FINDING_STATUS_ENUM = ENUM(
    FindingStatus,
    name="finding_status",
    schema="core",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class SlaConfiguration(Base):
    __tablename__ = "sla_configuration"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    critical_days: Mapped[int] = mapped_column(Integer, nullable=False)
    high_days: Mapped[int] = mapped_column(Integer, nullable=False)
    medium_days: Mapped[int] = mapped_column(Integer, nullable=False)
    low_days: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("critical_days > 0", name="critical_days_positive"),
        CheckConstraint("high_days > 0", name="high_days_positive"),
        CheckConstraint("medium_days > 0", name="medium_days_positive"),
        CheckConstraint("low_days > 0", name="low_days_positive"),
    )


class ProductType(Base):
    __tablename__ = "product_type"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    products: Mapped[list[Product]] = relationship(back_populates="product_type")


class Product(Base):
    __tablename__ = "product"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product_type.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    business_criticality: Mapped[str | None] = mapped_column(Text)
    sla_configuration_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sla_configuration.id")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    product_type: Mapped[ProductType] = relationship(back_populates="products")
    engagements: Mapped[list[Engagement]] = relationship(back_populates="product")

    __table_args__ = (
        UniqueConstraint("product_type_id", "name", name="product_type_id"),
        CheckConstraint(
            "business_criticality IN "
            "('very_high','high','medium','low','very_low')",
            name="business_criticality_valid",
        ),
    )


class ScannerConfig(Base):
    __tablename__ = "scanner_config"

    scanner_key: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    dedup_algorithm: Mapped[str] = mapped_column(Text, nullable=False)
    hash_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    reimport_algorithm: Mapped[str] = mapped_column(Text, nullable=False)
    reimport_hash_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    static_tool: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    __table_args__ = (
        CheckConstraint(
            "dedup_algorithm IN "
            "('unique_id_from_tool','hash_code','unique_id_from_tool_or_hash_code')",
            name="dedup_algorithm_valid",
        ),
    )


class Engagement(Base):
    __tablename__ = "engagement"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    engagement_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'in_progress'")
    )
    deduplication_on_engagement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    target_start: Mapped[datetime.date | None] = mapped_column(Date)
    target_end: Mapped[datetime.date | None] = mapped_column(Date)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    product: Mapped[Product] = relationship(back_populates="engagements")
    tests: Mapped[list[Test]] = relationship(back_populates="engagement")

    __table_args__ = (
        CheckConstraint(
            "engagement_type IN ('interactive','ci_cd')", name="engagement_type_valid"
        ),
        CheckConstraint(
            "status IN ('not_started','in_progress','completed')", name="status_valid"
        ),
    )


class Component(Base):
    __tablename__ = "component"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    purl: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("name", "version", name="name"),)


class Test(Base):
    __tablename__ = "test"
    __test__ = False  # not a pytest test class, despite the name



    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    engagement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("engagement.id"), nullable=False
    )
    scanner_key: Mapped[str] = mapped_column(
        Text, ForeignKey("scanner_config.scanner_key"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(Text)
    service: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    engagement: Mapped[Engagement] = relationship(back_populates="tests")
    findings: Mapped[list[Finding]] = relationship(back_populates="test")


class Finding(Base):
    __tablename__ = "finding"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    test_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("test.id"), nullable=False)
    # Denormalized for dedup scope and authz. Immutable after creation (see ADR-0003:
    # an engagement cannot move between products in Phase 1).
    engagement_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[Severity] = mapped_column(SEVERITY_ENUM, nullable=False)
    status: Mapped[FindingStatus] = mapped_column(
        FINDING_STATUS_ENUM, nullable=False, server_default=text("'active'")
    )
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    description: Mapped[str | None] = mapped_column(Text)
    mitigation: Mapped[str | None] = mapped_column(Text)
    impact: Mapped[str | None] = mapped_column(Text)
    references_text: Mapped[str | None] = mapped_column(Text)
    cwe: Mapped[int | None] = mapped_column(Integer)
    vuln_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    cvss_v3_vector: Mapped[str | None] = mapped_column(Text)
    cvss_v3_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    epss_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    component_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("component.id")
    )
    file_path: Mapped[str | None] = mapped_column(Text)
    line: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    unique_id_from_tool: Mapped[str | None] = mapped_column(Text)
    vuln_id_from_tool: Mapped[str | None] = mapped_column(Text)
    hash_code: Mapped[str | None] = mapped_column(String(64))
    # Scanner-independent hash over the shared subset (vuln_ids + component + version), set
    # only when those exist, for cross-tool dedup (ADR-0011/0012). NULL = does not cross-dedup.
    cross_tool_hash: Mapped[str | None] = mapped_column(String(64))
    # The single string dedup/reimport compare on (uid, hash, or coalesce per scanner_config).
    # Stored so the reimport diff is a plain index lookup, not a CASE expression (3.7.4).
    match_key: Mapped[str | None] = mapped_column(Text)
    duplicate_of: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("finding.id"))
    sla_due_date: Mapped[datetime.date | None] = mapped_column(Date)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    mitigated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    raw_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    test: Mapped[Test] = relationship(back_populates="findings")
    component: Mapped[Component | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "duplicate_of IS NULL OR duplicate_of <> id", name="duplicate_of_not_self"
        ),
        CheckConstraint(
            "(status = 'mitigated') = (mitigated_at IS NOT NULL)",
            name="mitigated_at_consistency",
        ),
        # Reimport matching (scoped to one test): the hottest path in the system. The
        # match_key index serves the set-based reimport diff (3.7.4); hash/uid indexes remain
        # for cross-tool dedup and pre-match_key rows.
        Index("finding_test_matchkey", "test_id", "match_key"),
        Index("finding_test_hash", "test_id", "hash_code"),
        Index(
            "finding_test_uid",
            "test_id",
            "unique_id_from_tool",
            postgresql_where=text("unique_id_from_tool IS NOT NULL"),
        ),
        # Same-tool dedup (product scope); only originals are match targets.
        Index(
            "finding_product_hash",
            "product_id",
            "hash_code",
            postgresql_where=text("duplicate_of IS NULL"),
        ),
        # Cross-tool dedup (product scope, hash path, only findings that carry a shared key).
        Index(
            "finding_product_crosshash",
            "product_id",
            "cross_tool_hash",
            postgresql_where=text("duplicate_of IS NULL AND cross_tool_hash IS NOT NULL"),
        ),
        # UI list queries and keyset pagination.
        Index("finding_product_status", "product_id", "status", "severity", "id"),
        # SLA scheduler.
        Index(
            "finding_sla_due",
            "sla_due_date",
            postgresql_where=text("status = 'active'"),
        ),
        # "Which findings have CVE-X?"
        Index("finding_vuln_ids_gin", "vuln_ids", postgresql_using="gin"),
    )


class TestImport(Base):
    __tablename__ = "test_import"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    test_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("test.id"), nullable=False)
    import_job_id: Mapped[str] = mapped_column(
        String(36), nullable=False
    )  # UUID; cross-schema job lives in ingest (Phase 4)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    created_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    untouched_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    reactivated_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    closed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("kind IN ('import','reimport')", name="kind_valid"),
    )


class ReimportDecision(Base):
    """A reimport paused by the mass-closure circuit breaker, awaiting a human (ADR-0013).

    One row per reimport job that tripped the breaker. Holds the candidate close set so
    ``confirm`` can apply it later and ``reject`` can discard it. Kept after resolution for
    audit (``status`` moves needs_confirmation → confirmed|rejected); never deleted.
    """

    __tablename__ = "reimport_decision"

    import_job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    test_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("test.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'needs_confirmation'")
    )
    close_candidate_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, server_default=text("'{}'")
    )
    active_before: Mapped[int] = mapped_column(Integer, nullable=False)
    incoming_count: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_import_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('needs_confirmation','confirmed','rejected')",
            name="reimport_decision_status_valid",
        ),
    )


class AuditLog(Base):
    """Append-only audit log, partitioned by month on ``occurred_at``.

    Partitioning (PARTITION BY RANGE) and the monthly partitions are created in the
    migration; SQLAlchemy cannot express them. The composite PK (id, occurred_at) is
    required because the partition key must be part of the primary key.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[dict[str, object] | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user','system','import')", name="actor_type_valid"
        ),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )


# ---------------------------------------------------------------------------
# RBAC (project.md 2.8). Role columns are text + CHECK (not a PG enum) so the role
# set can evolve without an enum migration (ADR-0005).
# ---------------------------------------------------------------------------
_ROLE_CHECK = "IN ('reader','api_importer','writer','maintainer','owner')"


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # Keycloak sub
    username: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    global_role: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"global_role {_ROLE_CHECK}", name="global_role_valid"),
    )


class ProductTypeMember(Base):
    __tablename__ = "product_type_member"

    product_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product_type.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint(f"role {_ROLE_CHECK}", name="role_valid"),)


class ProductMember(Base):
    __tablename__ = "product_member"

    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint(f"role {_ROLE_CHECK}", name="role_valid"),)


class UserProductAccess(Base):
    """Effective per-user, per-product access. Maintained from product_member and
    product_type_member (and global roles). The single table every finding query joins
    against for RBAC (project.md 2.8)."""

    __tablename__ = "user_product_access"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("product.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint(f"role {_ROLE_CHECK}", name="role_valid"),)


class ApiToken(Base):
    """Scoped CI tokens: random 32-byte secret, stored only as a SHA-256 hex hash,
    scoped to products and actions, with expiry (project.md 3.10)."""

    __tablename__ = "api_token"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scope_product_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, server_default=text("'{}'")
    )
    scope_actions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
