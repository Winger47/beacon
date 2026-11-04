# ADR-0010: Severity normalization across scanners

- Status: accepted
- Date: 2026-11-04

## Context
`core.finding.severity` is a single ordinal enum — `info < low < medium < high < critical`
(ADR-0002 keeps it as the one severity scale). Scanners disagree on both vocabulary and scale:

- Trivy / Grype: `CRITICAL | HIGH | MEDIUM | LOW | UNKNOWN`.
- Some advisories: `moderate` (= medium), `negligible` (= info), `none`.
- CVSS-only tools: a numeric base score (0.0–10.0) and no word.
- SARIF tools: `error | warning | note | none` (a *level*, not a severity) plus an optional
  `security-severity` CVSS number.

The parser must turn any of these into one of five labels, deterministically, without ever
losing information a triager might want.

## Options considered
| Option | Pros | Cons |
|---|---|---|
| Derive severity from CVSS score in the parser (score → band) | Uniform; works for CVSS-only tools | Overrides the tool's own stated severity; two tools with the same CVE but different bands now disagree for a reason we invented; hides the tool's judgement |
| Per-scanner severity map baked into each parser | Maximum fidelity | Duplicated logic; drift between parsers; every new vocabulary edits code |
| **One shared `Severity.from_text` table; tool's stated word wins; CVSS kept as data, not used to pick the band; unknown → `info`** | One place to reason about; deterministic; faithful to the tool; preserves CVSS for triage/sort | `info` floor for unknowns can under-rank a genuinely unknown-but-real issue (accepted; surfaced via `verified`/triage) |

## Decision
1. Normalization lives in **one** function, `kata_parsers.Severity.from_text`, used by every
   parser. The mapping is fixed and case-insensitive:
   - `critical → critical`
   - `high → high`
   - `medium`, `moderate → medium`
   - `low → low`
   - `info`, `informational`, `unknown`, `negligible`, `none`, *missing* → `info`
2. **The tool's stated severity wins.** The parser does **not** compute severity from the CVSS
   score, even when present. `cvss_v3_score` / `cvss_v3_vector` are carried as their own fields
   for display, sorting and later risk scoring — never to re-bucket severity. Rationale: if
   Trivy says HIGH and its CVSS base is 9.1, we honor HIGH; re-banding would silently contradict
   the scanner and make cross-tool dedup (Phase 3) compare apples we bent into oranges.
3. **Unknown maps to `info`, not an error.** A severity we do not recognise must never fail an
   import; it is floored to `info` and the raw token is preserved in `Finding.extra`
   (`extra["severity_raw"]`) when it differs from the mapped label, so no information is lost.
4. SARIF `level` is **not** a severity and is handled in the SARIF parser (Phase 5): it maps
   `error→high, warning→medium, note→low, none→info` *only as a fallback* when the result has no
   `security-severity`; this is recorded again in that parser's ADR when it lands.
5. Cross-tool severity conflicts (same finding, two tools, two severities) are a **dedup**
   concern, not a parser concern: the original keeps its severity; Phase 3 decides. (This is the
   project.md Phase 3 "think first" question; flagged here, answered there.)

## Consequences
- **Easier:** one table to audit; every parser normalizes identically; adding a vocabulary is a
  one-line map edit with a test; CVSS stays available for a future EPSS/risk sort.
- **Harder:** a flood of `unknown`-severity items all land at `info` and can hide under triage
  defaults — mitigated by keeping `severity_raw` and by the `verified` flag. The `from_text`
  table is now a shared contract; changing a mapping is a behavioral change that needs a test
  update and, if it moves many findings, a recompute (Phase 3 management command).

## How DefectDojo does it
Similar in spirit, messier in practice. DefectDojo normalizes to
`Info/Low/Medium/High/Critical` but each parser contains its own mapping, and several parsers
*do* derive severity from CVSS when the tool omits a word — which is exactly the behavior we
reject in point 2 to keep cross-tool comparisons honest. Kata centralizes the table and makes
"tool's word wins, CVSS is data" an explicit rule. (Behavioral reference only; no code copied.)

## Revisit when
A real scanner reports a severity token we map to `info` that is consistently a true
high-severity issue (add the token), or Phase 3 shows cross-tool dedup needs a severity-reconcile
policy richer than "original wins" (write that policy as its own ADR).
