"""Repository layer: all data access for the core domain.

Business/domain logic lives here (CLAUDE.md #5), not in route handlers. The single
authorized findings query (``list_findings``) applies RBAC in the data layer: every finding
query is scoped to the principal's accessible products (project.md 2.8). No finding query may
bypass this.
"""

from __future__ import annotations

import base64
import binascii
import datetime
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from .enums import FindingStatus, Role, Severity
from .models import (
    ApiToken,
    Component,
    Engagement,
    Finding,
    Product,
    ProductMember,
    ProductType,
    ProductTypeMember,
    ReimportDecision,
    ScannerConfig,
    Test,
    TestImport,
    UserProductAccess,
)

# Global roles that grant read access to every product (API_IMPORTER does not).
_READ_ALL_GLOBAL_ROLES = frozenset({Role.READER, Role.WRITER, Role.MAINTAINER, Role.OWNER})


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated identity a query runs as."""

    user_id: int
    global_role: Role | None = None

    @property
    def can_read_all_products(self) -> bool:
        return self.global_role in _READ_ALL_GLOBAL_ROLES


@dataclass(frozen=True, slots=True)
class Cursor:
    """Keyset cursor: the (severity, id) of the last row seen."""

    severity: Severity
    finding_id: int

    def encode(self) -> str:
        raw = f"{self.severity.value}:{self.finding_id}".encode()
        return base64.urlsafe_b64encode(raw).decode()

    @classmethod
    def decode(cls, token: str) -> Cursor:
        try:
            raw = base64.urlsafe_b64decode(token.encode()).decode()
            sev, fid = raw.rsplit(":", 1)
            return cls(severity=Severity(sev), finding_id=int(fid))
        except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
            raise ValueError("invalid cursor") from exc


@dataclass(frozen=True, slots=True)
class FindingPage:
    findings: Sequence[Finding]
    next_cursor: str | None


def _rbac_predicate(principal: Principal) -> ColumnElement[bool] | None:
    """WHERE clause restricting findings to the principal's products, or None for read-all."""
    if principal.can_read_all_products:
        return None
    accessible = select(UserProductAccess.product_id).where(
        UserProductAccess.user_id == principal.user_id
    )
    return Finding.product_id.in_(accessible)


def list_findings(
    session: Session,
    principal: Principal,
    *,
    product_id: int | None = None,
    test_id: int | None = None,
    status: FindingStatus | None = None,
    severity: Severity | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> FindingPage:
    """Return a keyset-paginated page of findings the principal may see.

    Ordering is (severity DESC, id DESC): most severe and newest first, deterministic.
    The cursor encodes the (severity, id) of the last row, so paging stays fast at any
    depth (no OFFSET scan). Uses the finding_product_status index for the common
    single-product case.
    """
    limit = max(1, min(limit, 1000))
    stmt = select(Finding)

    rbac = _rbac_predicate(principal)
    if rbac is not None:
        stmt = stmt.where(rbac)
    if product_id is not None:
        stmt = stmt.where(Finding.product_id == product_id)
    if test_id is not None:
        stmt = stmt.where(Finding.test_id == test_id)
    if status is not None:
        stmt = stmt.where(Finding.status == status)
    if severity is not None:
        stmt = stmt.where(Finding.severity == severity)

    if cursor is not None:
        c = Cursor.decode(cursor)
        # SQL row-value comparison on (severity, id) with DESC ordering: strictly "after".
        # tuple_() renders a real `(severity, id) < (:sev, :id)`; the column types bind
        # :sev as the enum so ordering matches ORDER BY severity.
        stmt = stmt.where(
            tuple_(Finding.severity, Finding.id) < (c.severity.value, c.finding_id)
        )

    stmt = stmt.order_by(Finding.severity.desc(), Finding.id.desc()).limit(limit + 1)
    rows = list(session.scalars(stmt).all())

    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = Cursor(severity=last.severity, finding_id=last.id).encode()
    return FindingPage(findings=rows, next_cursor=next_cursor)


# --------------------------------------------------------------------------- RBAC maintenance
def recompute_user_product_access(session: Session, user_id: int) -> int:
    """Rebuild user_product_access for one user from direct product memberships and
    product-type memberships (set-based). Returns the number of effective rows.

    Direct product membership wins over a product-type membership for the same product;
    we keep the highest-ranked role via a simple precedence in Python-free SQL by taking
    the max over a role-rank mapping. For Phase 1 we keep it straightforward: direct
    membership role if present, else the product-type role.
    """
    session.query(UserProductAccess).filter(UserProductAccess.user_id == user_id).delete()

    # Products via direct membership.
    direct = select(ProductMember.product_id, ProductMember.role).where(
        ProductMember.user_id == user_id
    )
    # Products via product-type membership.
    via_type = (
        select(Product.id, ProductTypeMember.role)
        .join(ProductTypeMember, ProductTypeMember.product_type_id == Product.product_type_id)
        .where(ProductTypeMember.user_id == user_id)
    )

    effective: dict[int, str] = {}
    for pid, role in session.execute(via_type):
        effective[pid] = role
    for pid, role in session.execute(direct):  # direct overrides product-type
        effective[pid] = role

    session.add_all(
        UserProductAccess(user_id=user_id, product_id=pid, role=role)
        for pid, role in effective.items()
    )
    return len(effective)


# --------------------------------------------------------------------------- simple CRUD
def create_product_type(session: Session, name: str) -> ProductType:
    pt = ProductType(name=name)
    session.add(pt)
    session.flush()
    return pt


def create_product(session: Session, *, product_type_id: int, name: str) -> Product:
    p = Product(product_type_id=product_type_id, name=name)
    session.add(p)
    session.flush()
    return p


def create_engagement(
    session: Session, *, product_id: int, name: str, engagement_type: str = "ci_cd"
) -> Engagement:
    e = Engagement(product_id=product_id, name=name, engagement_type=engagement_type)
    session.add(e)
    session.flush()
    return e


def create_test(
    session: Session, *, engagement_id: int, scanner_key: str, title: str | None = None
) -> Test:
    t = Test(engagement_id=engagement_id, scanner_key=scanner_key, title=title)
    session.add(t)
    session.flush()
    return t


def get_product(session: Session, product_id: int) -> Product | None:
    return session.get(Product, product_id)


def get_scanner_config(session: Session, scanner_key: str) -> ScannerConfig | None:
    return session.get(ScannerConfig, scanner_key)


def get_reimport_decision(session: Session, import_job_id: str) -> ReimportDecision | None:
    return session.get(ReimportDecision, import_job_id)


def list_pending_decisions(session: Session, *, test_id: int) -> list[ReimportDecision]:
    """Unresolved mass-closure pauses for a test, newest first (Test page confirm/reject UI)."""
    return list(
        session.scalars(
            select(ReimportDecision)
            .where(
                ReimportDecision.test_id == test_id,
                ReimportDecision.status == "needs_confirmation",
            )
            .order_by(ReimportDecision.created_at.desc())
        ).all()
    )


def get_test(session: Session, test_id: int) -> Test | None:
    return session.get(Test, test_id)


def list_tests(session: Session, *, engagement_id: int) -> list[Test]:
    """Tests in an engagement, newest first (for the UI import history list)."""
    return list(
        session.scalars(
            select(Test)
            .where(Test.engagement_id == engagement_id)
            .order_by(Test.id.desc())
        ).all()
    )


def list_test_imports(session: Session, *, test_id: int) -> list[TestImport]:
    """Import/reimport rows for a test, newest first (Test page timeline)."""
    return list(
        session.scalars(
            select(TestImport)
            .where(TestImport.test_id == test_id)
            .order_by(TestImport.id.desc())
        ).all()
    )


def get_or_create_component(session: Session, *, name: str, version: str) -> Component:
    comp = session.scalar(
        select(Component).where(Component.name == name, Component.version == version)
    )
    if comp is None:
        comp = Component(name=name, version=version)
        session.add(comp)
        session.flush()
    return comp


def add_finding(session: Session, finding: Finding) -> Finding:
    """Insert a pre-built finding (import path). Dedup/hashing is Phase 3; FSM is Phase 4."""
    session.add(finding)
    return finding


def create_test_import(
    session: Session,
    *,
    test_id: int,
    import_job_id: str,
    kind: str,
    created_count: int = 0,
    untouched_count: int = 0,
    reactivated_count: int = 0,
    closed_count: int = 0,
) -> TestImport:
    row = TestImport(
        test_id=test_id,
        import_job_id=import_job_id,
        kind=kind,
        created_count=created_count,
        untouched_count=untouched_count,
        reactivated_count=reactivated_count,
        closed_count=closed_count,
    )
    session.add(row)
    session.flush()
    return row


def effective_role(session: Session, principal: Principal, product_id: int) -> Role | None:
    """The principal's effective role on a product: global role if read-all, else the
    user_product_access role. None if no access."""
    if principal.global_role is not None and principal.can_read_all_products:
        return principal.global_role
    row = session.execute(
        select(UserProductAccess.role).where(
            UserProductAccess.user_id == principal.user_id,
            UserProductAccess.product_id == product_id,
        )
    ).scalar_one_or_none()
    return Role(row) if row is not None else None


def get_finding_authorized(
    session: Session, principal: Principal, finding_id: int
) -> Finding | None:
    """Fetch a finding only if the principal may see it; else None (404, no existence leak)."""
    finding = session.get(Finding, finding_id)
    if finding is None:
        return None
    if principal.can_read_all_products:
        return finding
    role = effective_role(session, principal, finding.product_id)
    return finding if role is not None else None


def list_api_tokens(session: Session, user_id: int) -> Sequence[ApiToken]:
    return list(
        session.scalars(
            select(ApiToken).where(ApiToken.user_id == user_id).order_by(ApiToken.id)
        ).all()
    )


def revoke_api_token(session: Session, *, user_id: int, token_id: int) -> bool:
    """Revoke a token owned by the user. Returns False if not found / not theirs."""
    token = session.get(ApiToken, token_id)
    if token is None or token.user_id != user_id:
        return False
    if token.revoked_at is None:
        token.revoked_at = datetime.datetime.now(tz=datetime.UTC)
    return True


def list_products(session: Session, principal: Principal) -> Sequence[Product]:
    stmt = select(Product).order_by(Product.id)
    if not principal.can_read_all_products:
        accessible = select(UserProductAccess.product_id).where(
            UserProductAccess.user_id == principal.user_id
        )
        stmt = stmt.where(Product.id.in_(accessible))
    return list(session.execute(stmt).scalars().all())
