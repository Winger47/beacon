# ADR-0002: Single finding status enum instead of independent booleans

- Status: accepted
- Date: 2026-11-03

## Context

A finding's state must capture: open/active, fixed, false positive, out of scope, risk
accepted, and (optionally) under review, plus whether it is a duplicate and whether it is
verified. DefectDojo models this with several independent booleans (`active`, `verified`,
`false_p`, `out_of_scope`, `risk_accepted`, `is_mitigated`, `duplicate`, ...). Independent
booleans allow invalid combinations (e.g. active *and* mitigated) and make reimport logic
branch on many flags.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| Independent booleans (DefectDojo) | Can express overlaps like "false positive AND mitigated"; matches the reference system | Invalid states representable; reimport/dedup logic must reason about flag combinations; no single source of truth for "what state is this?" |
| Single `status` enum + `verified` flag + `duplicate_of` ref (**chosen**) | Invalid states unrepresentable; one obvious transition graph; simpler reimport; a DB CHECK can tie `mitigated_at` to status | Cannot express two triage facts at once (e.g. false-positive *and* mitigated); a small expressiveness loss |

## Decision

Use a single `core.finding_status` enum (`active`, `mitigated`, `false_positive`,
`out_of_scope`, `risk_accepted`, `under_review`), plus a separate `verified` boolean and a
`duplicate_of` self-reference. Status changes go through one `transition()` function
(ADR-0004) governed by an explicit allowed-edge table. A CHECK constraint enforces
`(status = 'mitigated') = (mitigated_at IS NOT NULL)`.

## Consequences

- Easier: the transition graph is explicit and testable (every edge has a unit test);
  reimport maps cleanly to create / untouched / reactivate / close; metrics group by one column.
- Harder: we give up simultaneous triage facts. If a real need appears (e.g. "this is a
  false positive that was also auto-closed"), we revisit — likely with a separate
  `triage_disposition` field rather than reintroducing boolean soup.
- Must monitor: whether any workflow genuinely needs overlapping states; the parity harness
  (Phase 3) will surface divergences from DefectDojo.

## How DefectDojo does it

Independent booleans, open source. We deliberately diverge; the parity doc (Phase 3) records
where outcomes differ because of it.

## Revisit when

A concrete, recurring triage need cannot be expressed as a single status plus `verified` +
`duplicate_of`.
