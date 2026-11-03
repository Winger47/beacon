"""Repository layer: all data access for the core domain.

Business/domain logic lives here (CLAUDE.md #5), not in route handlers. The single
authorized findings query (``list_findings``) applies RBAC in the data layer: every finding
query is scoped to the principal's accessible products (project.md 2.8). No finding query may
bypass this.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from .enums import FindingStatus, Role, Severity
from .models import (
    Engagement,
    Finding,
    Product,
    ProductMember,
    ProductType,
    ProductTypeMember,
    Test,
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


def list_products(session: Session, principal: Principal) -> Sequence[Product]:
    stmt = select(Product).order_by(Product.id)
    if not principal.can_read_all_products:
        accessible = select(UserProductAccess.product_id).where(
            UserProductAccess.user_id == principal.user_id
        )
        stmt = stmt.where(Product.id.in_(accessible))
    return list(session.execute(stmt).scalars().all())
