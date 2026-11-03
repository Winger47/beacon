# ADR-0003: Denormalized product_id/engagement_id on finding; engagement cannot move products

- Status: accepted
- Date: 2026-11-03

## Context

`core.finding` denormalizes `product_id` and `engagement_id` (project.md 3.2) so that the two
hottest concerns — dedup scoping (product/engagement) and RBAC filtering — are plain indexed
column predicates, not multi-level joins up the hierarchy on every query at 10M+ rows.

Denormalization raises a correctness question (the Phase 1 "think first"): what happens when
an engagement is moved to a different product? Every child finding's denormalized `product_id`
would be stale, the dedup scope would shift (an "original" could now sit in a different
product than its "duplicates"), and RBAC visibility could change silently.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| Allow engagement move, fix denormalized columns lazily | Flexible | Stale `product_id` until fixed; dedup/RBAC wrong in the gap; easy to get subtly wrong |
| Allow engagement move as an atomic, audited, set-based operation | Flexible and correct | Must rewrite all child findings, re-run dedup scoping, re-evaluate RBAC in one transaction; heavy; rare |
| Forbid engagement move in Phase 1 (**chosen**) | Removes the whole class of bug now; keeps denormalization safe | Users cannot re-parent an engagement (acceptable; DefectDojo users rarely do, and it is disruptive there too) |

## Decision

`engagement.product_id` is **immutable after creation**. No API path updates it. Enforced by
an application-level guard plus a test; a DB rule/trigger backstop may be added if needed. The
denormalized `finding.product_id` / `finding.engagement_id` are therefore set once at insert
and never drift. Creating a new engagement under the correct product is the supported path.

## Consequences

- Easier: dedup scope and RBAC predicates stay correct by construction; no reconciliation job.
- Harder: no re-parenting. If ever required, it becomes a dedicated, audited, set-based
  migration operation with its own ADR (rewrite findings, re-scope dedup, re-evaluate access).
- Must monitor: user demand for moving engagements; any code path that tries to mutate
  `engagement.product_id` must fail a test.

## How DefectDojo does it

DefectDojo permits some re-parenting through its admin, which can make historical scoping
fuzzy. We trade that flexibility for invariant-by-construction scoping. Recorded in the parity
doc.

## Revisit when

There is real, repeated demand to move engagements between products, justifying the atomic
re-scope operation.
