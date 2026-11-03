# ADR-0006: Keyset pagination for finding lists

- Status: accepted
- Date: 2026-11-03

## Context

Finding lists must stay fast at 10M+ rows (p95 < 300 ms). Offset pagination makes PostgreSQL
scan and discard all preceding rows, so latency grows with page depth. The UI also uses
infinite-scroll / virtualized tables, which fit a cursor model.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| Offset/limit | Trivial; "jump to page N" | O(offset) scan-and-discard; p95 degrades with depth; unstable under concurrent inserts |
| Keyset (chosen) | O(log n) via index; flat latency at any depth; stable under inserts | No "jump to page 9,431" (nobody needs it) |

## Decision

Keyset pagination ordered by `(severity DESC, id DESC)`. The cursor is an opaque
base64 of `severity:id` of the last row. The "next page" predicate is a SQL row-value
comparison `ROW(severity, id) < ROW(:sev, :id)`, served by the composite index
`finding_product_status (product_id, status, severity, id)` — the predicate pushes into the
Index Cond and the `ORDER BY` is a backward index scan.

Implementation detail learned: use SQLAlchemy `tuple_(...)` for the row-value comparison. A
plain Python tuple comparison does **not** render SQL row-value semantics and silently
produces wrong results.

## Consequences

- Easier: flat p95 regardless of depth (measured 1.6 ms at 1M rows, ~190× under budget);
  stable paging under concurrent inserts.
- Harder: no random page access; cursors are opaque and must be validated (a bad cursor is a
  400, not a 500).
- Must monitor: the cross-product (RBAC-scoped, multi-product) list has a different access
  pattern; benchmark it separately when it matters (Phase 8).

## How DefectDojo does it

DefectDojo's API uses offset/limit (DRF default). Kata deliberately diverges for depth
stability; recorded in the parity doc.

## Revisit when

A real need for random page access appears, or the ordering key must change (then the cursor
format and index change together).
