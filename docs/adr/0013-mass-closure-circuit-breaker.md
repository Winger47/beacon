# ADR-0013: Mass-closure circuit breaker and NEEDS_CONFIRMATION

- Status: accepted
- Date: 2026-11-06

## Context

Reimport with `close_old_findings` closes every active finding in a Test whose match key is
absent from the new report. A **truncated or failed CI artifact** — an empty or half-written
report uploaded as "the latest scan" — would then mark thousands of real, unfixed
vulnerabilities as `mitigated`. This is the single most dangerous operation in the system
(project.md 2.9, 3.7.4).

We need an automatic guard that distinguishes "the team genuinely fixed a lot" from "the
report is broken", without blocking normal small reductions.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| No guard, trust the report | Simple | One bad CI run silently closes 40k findings |
| Absolute threshold (e.g. never close > N) | Easy to reason about | Wrong at every scale; 50 is huge for one Test, nothing for another |
| **Percentage + shrink guard, pause to NEEDS_CONFIRMATION** (chosen) | Scales with Test size; catches truncation specifically; human decides | Needs a pending state + confirm/reject flow |

## Decision

At finalization, compute `to_close` (active findings not seen this job) and `active_before`.
Trip the breaker when **both**:

1. `to_close / active_before > CLOSE_RATIO` (default **0.50**), and
2. the incoming report is much smaller than the previous one:
   `incoming_count < PREV_RATIO * previous_import_count` (default **0.50**).

Condition 2 is what separates a real fix campaign (report still roughly the same size, most
findings simply resolved) from truncation (report collapsed to a fraction). Both must hold;
a Test with very few findings is exempted by a floor (`active_before >= MIN_FINDINGS`,
default **10**) so tiny Tests don't false-trip.

When tripped, the reimport does **not** close anything. It:
- persists the pending close set (the candidate finding ids) and the computed counts on a
  `reimport_decision` row keyed by `import_job_id`, status `needs_confirmation`,
- records the `test_import` row with the created/reactivated/untouched counts already applied
  and `closed_count = 0`,
- returns `NEEDS_CONFIRMATION` with the preview counts.

Two endpoints resolve it (WRITER on the product):
- `POST /api/v1/reimport/{job_id}/confirm` → runs the close via `bulk_transition()`, updates
  the `test_import.closed_count`, marks the decision `confirmed`.
- `POST /api/v1/reimport/{job_id}/reject` → closes nothing, marks the decision `rejected`;
  the active findings stay active.

Thresholds live in config (`KATA_CLOSE_RATIO`, `KATA_CLOSE_PREV_RATIO`,
`KATA_CLOSE_MIN_FINDINGS`) so they are tunable without a deploy.

**Human-triaged statuses are never auto-closed** regardless of the breaker: `false_positive`,
`out_of_scope`, `risk_accepted` findings absent from a report keep their status (3.7.4 step
7 operates only on `status='active'`).

## Consequences

- A broken CI upload pauses instead of destroying triage state; the owner sees a diff preview
  and decides.
- A new pending state and two endpoints exist; the decision row must be cleaned up (kept for
  audit, not deleted).
- Everything the reimport already applied (creates, reactivations) is kept when it pauses —
  only closure waits. Re-running the same job id is a no-op on those (idempotent via
  `applied_batch` / the `status = :from` guard).

## How DefectDojo does it

DefectDojo closes old findings on reimport without a built-in truncation circuit breaker;
operators rely on `close_old_findings` being off or on review. The breaker and
`NEEDS_CONFIRMATION` are a **Kata extension** (project.md labels it so) addressing a known
operational foot-gun.

## Revisit when

The breaker false-trips on legitimate large fixes often enough to annoy teams (tune ratios),
or we need per-product thresholds instead of global ones.
