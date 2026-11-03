"""Phase 1 exit criterion: a Reader cannot see another product's findings (data-layer RBAC)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from kata_domain.enums import Role, Severity
from kata_domain.models import (
    AppUser,
    Engagement,
    Finding,
    Product,
    ProductMember,
    ProductType,
    ScannerConfig,
    Test,
)
from kata_domain.repositories import (
    Principal,
    list_findings,
    list_products,
    recompute_user_product_access,
)


def _scanner(db: Session) -> None:
    db.add(
        ScannerConfig(
            scanner_key="rbactest",
            display_name="Trivy",
            dedup_algorithm="hash_code",
            hash_fields=["title"],
            reimport_algorithm="hash_code",
            reimport_hash_fields=["title"],
        )
    )
    db.flush()


def _product_with_findings(db: Session, pt_id: int, name: str, n: int) -> Product:
    product = Product(product_type_id=pt_id, name=name)
    db.add(product)
    db.flush()
    eng = Engagement(product_id=product.id, name="e", engagement_type="ci_cd")
    db.add(eng)
    db.flush()
    test = Test(engagement_id=eng.id, scanner_key="rbactest", title="t")
    db.add(test)
    db.flush()
    for i in range(n):
        db.add(
            Finding(
                test_id=test.id,
                engagement_id=eng.id,
                product_id=product.id,
                title=f"{name}-{i}",
                severity=Severity.HIGH,
            )
        )
    db.flush()
    return product


def test_reader_cannot_see_other_products_findings(db: Session) -> None:
    pt = ProductType(name="pt")
    db.add(pt)
    db.flush()
    _scanner(db)

    product_a = _product_with_findings(db, pt.id, "A", 3)
    product_b = _product_with_findings(db, pt.id, "B", 2)

    reader = AppUser(subject="s-reader", username="reader")
    db.add(reader)
    db.flush()
    db.add(ProductMember(product_id=product_a.id, user_id=reader.id, role=Role.READER.value))
    db.flush()
    assert recompute_user_product_access(db, reader.id) == 1
    db.flush()

    principal = Principal(user_id=reader.id, global_role=None)

    # Reader sees only product A's findings.
    page = list_findings(db, principal, limit=100)
    seen_products = {f.product_id for f in page.findings}
    assert seen_products == {product_a.id}
    assert len(page.findings) == 3

    # Explicitly asking for product B returns nothing (RBAC excludes it) — no existence leak.
    page_b = list_findings(db, principal, product_id=product_b.id, limit=100)
    assert list(page_b.findings) == []

    # Reader's product list also excludes B.
    assert {p.id for p in list_products(db, principal)} == {product_a.id}


def test_global_reader_sees_all_products(db: Session) -> None:
    pt = ProductType(name="pt")
    db.add(pt)
    db.flush()
    _scanner(db)
    a = _product_with_findings(db, pt.id, "A", 3)
    b = _product_with_findings(db, pt.id, "B", 2)

    admin = AppUser(subject="s-admin", username="admin", global_role=Role.READER.value)
    db.add(admin)
    db.flush()

    principal = Principal(user_id=admin.id, global_role=Role.READER)
    # A global reader is not restricted to memberships: it can reach both products.
    # (Assert per-product so the test is robust to other data, e.g. a seeded DB.)
    assert len(list_findings(db, principal, product_id=a.id, limit=100).findings) == 3
    assert len(list_findings(db, principal, product_id=b.id, limit=100).findings) == 2
