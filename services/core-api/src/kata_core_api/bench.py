"""Benchmark: keyset finding-list latency at depth (Phase 1 exit criterion: p95 < 300 ms).

Runs many single-product, status-filtered keyset queries starting from random cursor
depths, so it measures the "any page is fast" property — not just the first page.

Usage:
    python -m kata_core_api.bench --iterations 300 --limit 100
"""

from __future__ import annotations

import argparse
import random
import time

from sqlalchemy import func, select

from kata_core_api.db import make_engine, make_session_factory
from kata_domain.enums import FindingStatus, Role, Severity
from kata_domain.models import Finding
from kata_domain.repositories import Cursor, Principal, list_findings


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[k]


def run(*, iterations: int, limit: int) -> dict[str, float]:
    engine = make_engine()
    factory = make_session_factory(engine)
    principal = Principal(user_id=0, global_role=Role.READER)
    rng = random.Random(7)
    severities = list(Severity)

    with factory() as session:
        # Pick the busiest product and the id range to draw random cursors from.
        product_id = session.execute(
            select(Finding.product_id)
            .group_by(Finding.product_id)
            .order_by(func.count().desc())
            .limit(1)
        ).scalar_one()
        min_id, max_id = session.execute(
            select(func.min(Finding.id), func.max(Finding.id)).where(
                Finding.product_id == product_id
            )
        ).one()

        # Warm up.
        for _ in range(5):
            list_findings(
                session, principal, product_id=product_id, status=FindingStatus.ACTIVE, limit=limit
            )

        latencies_ms: list[float] = []
        for _ in range(iterations):
            # Random cursor depth across the id range.
            cursor = Cursor(
                severity=rng.choice(severities),
                finding_id=rng.randint(min_id, max_id),
            ).encode()
            start = time.perf_counter()
            list_findings(
                session,
                principal,
                product_id=product_id,
                status=FindingStatus.ACTIVE,
                limit=limit,
                cursor=cursor,
            )
            latencies_ms.append((time.perf_counter() - start) * 1000.0)

    return {
        "iterations": float(iterations),
        "limit": float(limit),
        "p50_ms": _percentile(latencies_ms, 50),
        "p95_ms": _percentile(latencies_ms, 95),
        "p99_ms": _percentile(latencies_ms, 99),
        "max_ms": max(latencies_ms),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark keyset finding-list latency.")
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    stats = run(iterations=args.iterations, limit=args.limit)
    print(
        f"keyset list: n={int(stats['iterations'])} limit={int(stats['limit'])} | "
        f"p50={stats['p50_ms']:.1f}ms p95={stats['p95_ms']:.1f}ms "
        f"p99={stats['p99_ms']:.1f}ms max={stats['max_ms']:.1f}ms"
    )


if __name__ == "__main__":
    main()
