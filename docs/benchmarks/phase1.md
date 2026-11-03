# Phase 1 benchmark — findings list, keyset pagination at 1M rows

**Exit criterion (project.md 5.4):** findings list p95 < 300 ms at 1M seeded findings.

## Setup

- Hardware: local dev machine (Apple Silicon), PostgreSQL 16 in Docker (`core` compose profile).
- Data: `make seed FINDINGS=1000000 PRODUCTS=50` — deterministic (`--seed 1234`).
  Status mix ≈ 80% active, 12% mitigated, 4% false_positive, 3% risk_accepted, 1% out_of_scope.
  Load time via `COPY`: **~15 s** for 1,000,000 findings.
- Query: single-product, `status='active'`, keyset-paginated, `ORDER BY severity DESC, id DESC`,
  `LIMIT 100`. Cursors drawn at **random depth** across the id range (not just page 1), so this
  measures "any page is fast", which is the point of keyset.
- Harness: `python -m kata_core_api.bench --iterations 300 --limit 100` (times the full
  `list_findings` call, including ORM hydration of 100 rows).

## Result

| Metric | Value |
|---|---|
| p50 | **1.1 ms** |
| p95 | **1.6 ms** |
| p99 | 1.9 ms |
| max | 11.2 ms |

p95 is **~190× under** the 300 ms budget. ✅

## Why it's fast — `EXPLAIN (ANALYZE, BUFFERS)`

```
Limit (actual time=0.018..1.368 rows=101 loops=1)
  Buffers: shared hit=78
  ->  Index Scan Backward using finding_product_status on finding
        Index Cond: ((product_id = 61) AND (status = 'active')
                     AND (ROW(severity, id) < ROW('high', 500000)))
        Buffers: shared hit=78
Execution Time: 1.404 ms
```

- The composite index `finding_product_status (product_id, status, severity, id)` serves the
  filter, the `ORDER BY` (backward scan), **and** the keyset predicate — the whole
  `ROW(severity, id) < ROW(...)` is pushed into the `Index Cond`.
- Only **78 shared buffers** touched regardless of page depth — no OFFSET scan-and-discard.
  Offset pagination at depth would read and throw away all preceding rows; keyset does not.

## Notes / future work

- This measures the common single-product list (the product-page query). The cross-product
  "global findings" list for a non-admin spans many products via the RBAC subquery; its
  behaviour at scale is a Phase 8 (metrics) concern and will get its own benchmark.
- Re-run anytime with `make seed && python -m kata_core_api.bench`.
