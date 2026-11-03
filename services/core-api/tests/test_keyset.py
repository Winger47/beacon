"""Keyset pagination correctness: full walk returns every row once, in order, no OFFSET."""

from __future__ import annotations

from sqlalchemy.orm import Session

from kata_domain.enums import Role, Severity
from kata_domain.models import Engagement, Finding, Product, ProductType, ScannerConfig, Test
from kata_domain.repositories import Cursor, Principal, list_findings


def _setup(db: Session, n: int) -> int:
    pt = ProductType(name="pt")
    db.add(pt)
    db.flush()
    db.add(
        ScannerConfig(
            scanner_key="keysettest",
            display_name="Trivy",
            dedup_algorithm="hash_code",
            hash_fields=["title"],
            reimport_algorithm="hash_code",
            reimport_hash_fields=["title"],
        )
    )
    product = Product(product_type_id=pt.id, name="A")
    db.add(product)
    db.flush()
    eng = Engagement(product_id=product.id, name="e", engagement_type="ci_cd")
    db.add(eng)
    db.flush()
    test = Test(engagement_id=eng.id, scanner_key="keysettest", title="t")
    db.add(test)
    db.flush()
    sevs = list(Severity)
    for i in range(n):
        db.add(
            Finding(
                test_id=test.id,
                engagement_id=eng.id,
                product_id=product.id,
                title=f"f-{i}",
                severity=sevs[i % len(sevs)],
            )
        )
    db.flush()
    return product.id


def test_cursor_roundtrip() -> None:
    c = Cursor(severity=Severity.HIGH, finding_id=123)
    assert Cursor.decode(c.encode()) == c


def test_full_walk_is_complete_and_ordered(db: Session) -> None:
    product_id = _setup(db, 25)
    # Global reader so this pagination test doesn't depend on per-product memberships.
    principal = Principal(user_id=0, global_role=Role.READER)

    collected: list[tuple[int, Severity]] = []
    cursor: str | None = None
    pages = 0
    while True:
        page = list_findings(db, principal, product_id=product_id, limit=7, cursor=cursor)
        collected.extend((f.id, f.severity) for f in page.findings)
        pages += 1
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
        assert pages < 100  # guard against non-termination

    # Every finding exactly once.
    ids = [fid for fid, _ in collected]
    assert len(ids) == 25
    assert len(set(ids)) == 25

    # Ordered by (severity DESC, id DESC): each step is strictly "less than" the previous.
    keys = [(sev, fid) for fid, sev in collected]
    severity_rank = {s: i for i, s in enumerate(Severity)}
    comparable = [(severity_rank[s], fid) for s, fid in keys]
    assert comparable == sorted(comparable, reverse=True)
