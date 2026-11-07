# ADR-0012: Dedup ordering, product keying, and set-based status changes

- Status: accepted
- Date: 2026-11-06

## Context

Two forces are in tension in the reconciler:

1. **CLAUDE.md #6**: every finding status change goes through `transition()` in kata-domain,
   which validates the edge, keeps `mitigated_at` consistent, and writes an audit row.
2. **CLAUDE.md #9**: anything touching many findings must be set-based SQL — no per-row
   queries in a loop. A reimport can reactivate or close tens of thousands of findings.

Calling the per-object `transition()` in a Python loop over 40,000 findings violates #9 and
is unusably slow. But bypassing it with a raw `UPDATE ... SET status` violates #6 and loses
the audit trail and the `mitigated_at` invariant.

Separately, same-tool dedup has a race (3.7.3): two concurrent imports in one product can
each create an "original" for the same hash, producing two originals and wrong duplicate
counts.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| Loop `transition()` per finding | Honors #6 literally | O(n) round trips; violates #9; too slow |
| Raw bulk `UPDATE` in the reconciler | Fast | Bypasses the single status-change path; no audit; invariant can drift |
| **`bulk_transition()` in kata-domain** (chosen) | One set-based `UPDATE` + one set-based audit `INSERT`; still the *only* sanctioned bulk path; keeps the invariant | A second status-change function to keep in lockstep with `transition()` |

For the create race: product-keyed processing vs. advisory locks vs. a dedup sweep.

## Decision

**Bulk status changes go through `bulk_transition()` in kata-domain**, the set-based sibling
of `transition()`. It:
- validates the single `from → to` edge against the same `ALLOWED_TRANSITIONS` table,
- performs one `UPDATE core.finding SET status=:to, mitigated_at=<consistent>, updated_at=now()
  WHERE id = ANY(:ids) AND status = :from` (the `status = :from` guard makes it idempotent
  and race-safe — a row already moved is not touched),
- inserts audit rows set-based: `INSERT INTO core.audit_log (...) SELECT ... FROM finding
  WHERE id = ANY(:ids)`,
- returns the ids actually changed.

No other code may write `finding.status`. #6 is preserved in spirit and letter: there are now
exactly two status-change functions, both in kata-domain, both auditing, both guarding the
`mitigated_at` CHECK. Route handlers and the reconciler call these, never raw SQL.

**Dedup ordering / create race: start with product keying.** In-process (Phase 3) a single
request processes one product's import serially, so no race exists yet. The set-based dedup
picks the **oldest** finding per `(product_id, hash_code)` as the original
(`MIN(id)`/`first_seen_at`) via a window function and points newer ones at it with
`duplicate_of`. When Phase 4 adds Kafka, messages are keyed by `product_id` so one consumer
owns a product's ordering (project.md 3.7.3). We measure before reaching for advisory locks.

**Duplicate promotion on delete**: deleting an original promotes the oldest remaining
duplicate of that hash to original (`duplicate_of = NULL`) and repoints the rest, set-based.

## Consequences

- Reimport and dedup scale to millions of rows in a handful of statements.
- Any new status-change requirement must be added to **both** `transition()` and
  `bulk_transition()`; a test asserts their edge tables are the same object.
- Audit rows from bulk changes carry `actor_type='import'` and the job id, distinguishing
  them from human single-finding transitions.
- Product keying means one enormous product cannot be parallelized; that is a deliberate
  Phase 9 problem, not a Phase 3 one.

## How DefectDojo does it

DefectDojo performs reimport status changes in bulk and keys dedup on the product (or
engagement when `deduplication_on_engagement`). It does not route bulk closes through its
single-finding save path, which is the audit gap we close with `bulk_transition()`.

## Revisit when

A single product's imports become a throughput bottleneck (move to advisory locks or a
sweep), or audit volume from bulk changes needs compaction.
