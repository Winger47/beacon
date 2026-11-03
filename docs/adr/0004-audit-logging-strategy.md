# ADR-0004: Audit logging in application code, with a DB trigger as tripwire

- Status: accepted
- Date: 2026-11-03

## Context

Every finding state change must produce an `audit_log` row, and (from Phase 7) a correlated
`outbox` event, written in the same transaction as the change. The Phase 1 "think first" asks:
should the audit write live in application code or in a PostgreSQL trigger?

## Options considered

| Option | Pros | Cons |
|---|---|---|
| DB trigger only | Impossible to bypass from any client; catches manual `psql` edits | Sees only the row diff — not the actor (user/system/import) or the reason; cannot build the outbox payload with trace headers; per-row firing is N+1 on bulk reconciler writes |
| Application code only (**primary, chosen**) | Knows actor, intent and reason; writes the correlated outbox row in the same commit; can batch audit rows set-based for bulk reconciler writes | Misses out-of-band writes (a stray `UPDATE`, manual `psql`) that skip `transition()` |
| Hybrid: app code primary + trigger tripwire (**chosen overall**) | Keeps the rich app-code audit; a defensive trigger catches bypasses | A little more DB machinery |

## Decision

Audit rows are written in application code inside `transition()` (and, for bulk imports, by the
reconciler set-based in the same transaction as the `COPY`/upsert — never per-row triggers).
`transition()` is the single allowed path for `finding.status` (CLAUDE.md #6). As defense in
depth we add: (a) the grep test (project.md 3.8) that fails if any code updates
`finding.status` outside `transition()`, and (b) later, a DB trigger on `core.finding` that
rejects or flags a status change not accompanied by an audit row in the same transaction.

What each approach *misses*, made explicit: a trigger misses the actor and reason and the
outbox correlation; app code misses out-of-band writes. The hybrid covers both.

## Consequences

- Easier: audit captures who/why/what; outbox stays transactional; bulk path avoids N+1.
- Harder: discipline required — all status writes go through `transition()`; the tripwire and
  test enforce it.
- Must monitor: any new write path to `finding.status`; the enforcement test must stay green.

## How DefectDojo does it

DefectDojo uses Django model history/signals in application code. We take the same app-code
stance and add the DB tripwire as a Kata-specific guard.

## Revisit when

The tripwire proves noisy or insufficient, or a performance issue appears on the bulk audit path.
