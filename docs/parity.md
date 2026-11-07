# Reimport parity harness

Phase 3 (project.md Part V) requires that Kata's reimport outcomes — the per-step
**created / untouched / reactivated / closed** counts — match DefectDojo's, or that every
difference is written down and justified. This document is the record; the harness lives in
`scripts/parity/`.

## What the harness does

It replays a fixed **sequence** of import/reimport steps (not a single file) and compares the
counts each backend reports against a backend-independent **oracle** computed from the sequence
itself (`scripts/parity/scenario.py`). The oracle is the primary check: it encodes the reimport
contract (project.md 3.7.4) in ~40 lines that share no code with `kata_domain`, so a bug in the
real diff cannot also corrupt the expectation. DefectDojo, when configured, is a second oracle.

Default sequence (`default_sequence()`), Trivy format, each `(CVE, pkg, version)` = one finding:

| Step | Action | Report | Oracle: created / untouched / reactivated / closed |
|------|--------|--------|----------------------------------------------------|
| v1 | import | A B C D E | 5 / 0 / 0 / 0 |
| v2 | reimport (close_old) | A B C F G | 2 / 3 / 0 / 2 |
| v3 | reimport (close_old) | A B C F G **D** | 0 / 5 / 1 / 0 |
| v4 | reimport (close_old, **do_not_reactivate**) | A B C F G **E** | 0 / 5 / 0 / 1 |

v2 keeps A/B/C, adds F/G, closes D/E. v3 regresses D (reactivated) and leaves E closed
(absent + already mitigated → not touched). v4 shows `do_not_reactivate`: E reappears but stays
mitigated, while D (now absent) closes.

## Running it

Kata only (the configured default — see the Phase 3 decision):

```bash
make up && make migrate          # Postgres + core-api, with KATA_DEV_AUTH=true
uv run python -m scripts.parity.run --base-url http://localhost:8001
# or: make parity
```

Exit code is non-zero on any mismatch, so it doubles as a CI gate. The oracle itself is unit
tested in `make test` (`scripts/parity/tests/`) and needs no running stack.

Add DefectDojo as a second backend by pointing the harness at a live instance:

```bash
export DEFECTDOJO_URL=https://defectdojo.example
export DEFECTDOJO_TOKEN=...            # API v2 token
export DEFECTDOJO_ENGAGEMENT_ID=42     # a pre-created engagement
uv run python -m scripts.parity.run
```

The DefectDojo driver (`backends.py::DefectDojoBackend`) calls only its public REST API v2
(`import-scan` / `reimport-scan`) — DefectDojo is a behavioral reference over the wire, never a
code reference (CLAUDE.md hard rule 1).

## Intentional differences from DefectDojo

These are deliberate and are **excluded** from the parity comparison (the default sequence
avoids tripping them so the count-for-count diff stays clean):

1. **Mass-closure circuit breaker (F23, ADR-0013).** DefectDojo closes whatever is missing from
   a reimport, unconditionally. Kata pauses to `needs_confirmation` when a reimport would close
   more than `close_ratio` of an active set above `min_findings` *and* the incoming report
   shrank past `prev_ratio` (defaults 0.50 / 10 / 0.50). On a paused step Kata reports
   `closed = 0` with `close_candidates > 0`; DefectDojo would report the full closure. This is a
   safety feature, not a bug, so breaker-tripping sequences are out of the parity set and are
   covered by unit tests (`services/core-api/tests/test_reimport.py`) instead.

2. **Single status enum (ADR-0002).** DefectDojo tracks several boolean flags (`active`,
   `verified`, `is_mitigated`, `false_p`, `out_of_scope`, `risk_accepted`). Kata uses one status
   enum. "Closed by reimport" maps to `mitigated`; the four human-triaged DefectDojo flags map to
   `false_positive` / `out_of_scope` / `risk_accepted`. Counts are compared on the mapped states.

3. **Human-triaged statuses are never auto-closed.** In Kata a finding in `false_positive`,
   `out_of_scope`, or `risk_accepted` is never closed by `close_old_findings` (the human decision
   wins; reimport.py step 7 touches only `active`). DefectDojo's behavior here depends on its
   flags; where it differs, Kata's rule is authoritative and the harness does not drive triaged
   findings through the scanner path.

4. **`legacy` dedup algorithm not implemented (ADR-0011).** Kata implements `hash_code`,
   `unique_id_from_tool`, and `unique_id_from_tool_or_hash_code` only. Sequences are authored on
   the implemented algorithms.

## Status

- Oracle + sequence: implemented and unit-tested (`make test`).
- Kata backend: implemented; run against a local stack with `make parity`.
- DefectDojo backend: implemented against REST API v2; **not yet certified against a live
  instance** (no DefectDojo in the local stack — Phase 3 decision was "pluggable adapter, Kata
  now"). Certifying the two-sided diff requires standing up DefectDojo and supplying the three
  env vars above. Until then, parity is asserted against the oracle only.
