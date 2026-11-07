"""Deterministic synthetic seed: products, engagements, tests and N findings via COPY.

Findings are bulk-loaded with PostgreSQL COPY (not ORM inserts) so 1M rows load in
seconds. Deterministic given --seed, so benchmarks are reproducible.

Usage:
    python -m kata_core_api.seed --products 50 --findings 1000000
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import random
from collections.abc import Iterator

from sqlalchemy import Engine, delete, select

from kata_core_api.db import make_engine, make_session_factory, session_scope
from kata_domain.enums import FindingStatus, Severity
from kata_domain.models import Engagement, Product, ProductType, ScannerConfig, Test

SCANNERS = ["generic", "trivy", "grype", "kubescape", "sarif", "bandit"]

# Per-scanner dedup config (ADR-0011). (dedup_algorithm, hash_fields). reimport mirrors dedup
# in Phase 3. See the ADR for the rationale behind each field list.
_SCANNER_CONFIGS: dict[str, tuple[str, list[str]]] = {
    # SCA: CVE against a specific package@version is the identity; file/line absent.
    "trivy": ("hash_code", ["vuln_ids", "component_name", "component_version"]),
    "grype": ("hash_code", ["vuln_ids", "component_name", "component_version"]),
    # K8s posture: control id + control name + manifest path.
    "kubescape": (
        "unique_id_from_tool_or_hash_code",
        ["vuln_ids", "title", "file_path"],
    ),
    # SAST: rule id + rule + file (+ CWE); line deliberately excluded to avoid churn.
    "bandit": ("unique_id_from_tool_or_hash_code", ["vuln_ids", "title", "file_path", "cwe"]),
    "sarif": ("unique_id_from_tool_or_hash_code", ["vuln_ids", "title", "file_path", "cwe"]),
    # Kata generic format: everything in the key is caller-stable.
    "generic": ("hash_code", ["vuln_ids", "title", "file_path", "component_name"]),
}
_SEVERITIES = list(Severity)
# Steady state: most findings are active; a tail is triaged/closed.
_STATUS_WEIGHTS = [
    (FindingStatus.ACTIVE, 0.80),
    (FindingStatus.MITIGATED, 0.12),
    (FindingStatus.FALSE_POSITIVE, 0.04),
    (FindingStatus.RISK_ACCEPTED, 0.03),
    (FindingStatus.OUT_OF_SCOPE, 0.01),
]
_STATUSES = [s for s, _ in _STATUS_WEIGHTS]
_STATUS_CUM = [w for _, w in _STATUS_WEIGHTS]
# Fixed timestamp for mitigated findings, to satisfy the mitigated_at/status CHECK.
_MITIGATED_AT = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)


def _ensure_scanners(engine: Engine) -> None:
    """Upsert scanner_config with the ADR-0011 hash fields (updates placeholder rows too)."""
    factory = make_session_factory(engine)
    with session_scope(factory) as s:
        existing = {c.scanner_key: c for c in s.execute(select(ScannerConfig)).scalars()}
        for key in SCANNERS:
            algo, fields = _SCANNER_CONFIGS[key]
            row = existing.get(key)
            if row is None:
                s.add(
                    ScannerConfig(
                        scanner_key=key,
                        display_name=key.title(),
                        dedup_algorithm=algo,
                        hash_fields=fields,
                        reimport_algorithm=algo,
                        reimport_hash_fields=fields,
                    )
                )
            else:
                row.dedup_algorithm = algo
                row.hash_fields = fields
                row.reimport_algorithm = algo
                row.reimport_hash_fields = fields


def _build_hierarchy(engine: Engine, n_products: int) -> list[tuple[int, int, int]]:
    """Create product types, products, engagements, tests; return (test_id, eng_id, product_id)."""
    factory = make_session_factory(engine)
    triples: list[tuple[int, int, int]] = []
    with session_scope(factory) as s:
        n_types = max(1, n_products // 10)
        type_ids = []
        for i in range(n_types):
            pt = ProductType(name=f"seed-type-{i}")
            s.add(pt)
            s.flush()
            type_ids.append(pt.id)
        for p in range(n_products):
            product = Product(product_type_id=type_ids[p % n_types], name=f"seed-product-{p}")
            s.add(product)
            s.flush()
            eng = Engagement(product_id=product.id, name="ci-main", engagement_type="ci_cd")
            s.add(eng)
            s.flush()
            for scanner in SCANNERS:
                t = Test(engagement_id=eng.id, scanner_key=scanner, title=f"{scanner} scan")
                s.add(t)
                s.flush()
                triples.append((t.id, eng.id, product.id))
    return triples


def _pick_status(rng: random.Random) -> FindingStatus:
    r = rng.random()
    acc = 0.0
    for status, weight in zip(_STATUSES, _STATUS_CUM, strict=True):
        acc += weight
        if r < acc:
            return status
    return FindingStatus.ACTIVE


def _finding_rows(
    triples: list[tuple[int, int, int]], n: int, rng: random.Random
) -> Iterator[tuple[int, int, int, str, str, str, str, datetime.datetime | None]]:
    for i in range(n):
        test_id, eng_id, product_id = triples[i % len(triples)]
        sev = _SEVERITIES[rng.randrange(len(_SEVERITIES))]
        status = _pick_status(rng)
        title = f"CVE-2026-{i % 90000:05d} vuln in pkg-{i % 500}"
        h = hashlib.sha256(f"{product_id}:{title}:{i}".encode()).hexdigest()
        mitigated_at = _MITIGATED_AT if status is FindingStatus.MITIGATED else None
        yield (test_id, eng_id, product_id, title, sev.value, status.value, h, mitigated_at)


def seed(engine: Engine, *, n_products: int, n_findings: int, rng_seed: int) -> None:
    rng = random.Random(rng_seed)
    clear(engine)  # idempotent: remove any previous seed data first
    _ensure_scanners(engine)
    triples = _build_hierarchy(engine, n_products)

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        copy_sql = (
            "COPY core.finding "
            "(test_id, engagement_id, product_id, title, severity, status, hash_code, "
            "mitigated_at) FROM STDIN"
        )
        with cur.copy(copy_sql) as copy:
            for row in _finding_rows(triples, n_findings, rng):
                copy.write_row(row)
        raw.commit()
    finally:
        raw.close()


def clear(engine: Engine) -> None:
    """Remove previously seeded data only (scoped to seed-* names), findings first (FKs)."""
    factory = make_session_factory(engine)
    with session_scope(factory) as s:
        from kata_domain.models import Finding

        seed_products = select(Product.id).where(Product.name.like("seed-product-%"))
        seed_engagements = select(Engagement.id).where(Engagement.product_id.in_(seed_products))
        seed_tests = select(Test.id).where(Test.engagement_id.in_(seed_engagements))

        s.execute(delete(Finding).where(Finding.test_id.in_(seed_tests)))
        s.execute(delete(Test).where(Test.engagement_id.in_(seed_engagements)))
        s.execute(delete(Engagement).where(Engagement.product_id.in_(seed_products)))
        s.execute(delete(Product).where(Product.name.like("seed-product-%")))
        s.execute(delete(ProductType).where(ProductType.name.like("seed-type-%")))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed synthetic Kata data.")
    parser.add_argument("--products", type=int, default=50)
    parser.add_argument("--findings", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int, default=1234)
    args = parser.parse_args()

    engine = make_engine()
    seed(engine, n_products=args.products, n_findings=args.findings, rng_seed=args.seed)
    print(f"seeded {args.findings} findings across {args.products} products")


if __name__ == "__main__":
    main()
