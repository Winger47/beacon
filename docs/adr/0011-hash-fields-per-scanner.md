# ADR-0011: Hash field choices per scanner

- Status: accepted
- Date: 2026-11-06

## Context

Deduplication keys a finding by either the scanner's own unique id
(`unique_id_from_tool`) or a SHA-256 `hash_code` computed over a configured list of fields
(project.md 3.7.2). **Choosing which fields go into the hash is the real design work** — it
decides when two findings are "the same":

- Include volatile fields (`line`, `description`) and a finding "moves" (close + create)
  every time code shifts or the scanner rewrites advisory text — churn, false closures.
- Include too few fields and genuinely different findings collide into one.

The hash must also be stable across tools for cross-tool dedup (3.7.3), which needs fields
that exist in every tool's output (CVE + component + version), not tool-specific ones.

Normalization (`_norm` in 3.7.2) lowercases, trims, collapses whitespace, and sorts lists,
so field *order*, case, and whitespace never change the hash. Field names are embedded in
the hashed string (`field=value|...`) so swapping values between fields cannot collide.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| One field list for all scanners | Simple; one row to reason about | A SAST line finding and an SCA CVE finding have nothing in common; no single list fits both |
| Per-scanner list, chosen by finding *kind* (**chosen**) | Each tool keys on what is actually stable for it; cross-tool list is a deliberate subset | More config rows; each needs a written rationale |
| Always include `line`/`description` | Maximum specificity | Maximum churn; fails the "don't move findings when code shifts" test |

## Decision

Store per-scanner `hash_fields` (same-tool/cross-tool dedup) and `reimport_hash_fields`
(reimport matching within a Test) in `scanner_config`, plus the `dedup_algorithm` /
`reimport_algorithm`. The canonical field set a hash may draw from is the canonical Finding
(ADR-0009): `title`, `vuln_ids`, `cwe`, `component_name`, `component_version`, `file_path`,
`severity`, `description`, plus `unique_id_from_tool`.

A small set is **always** appended to every hash: `scanner_key`. This keeps two tools'
hashes in separate namespaces for same-tool dedup; cross-tool dedup uses a separate,
scanner-independent key expression (CVE + component + version) and so omits `scanner_key`.

Field choices and the rationale per scanner:

| Scanner | Kind | hash_fields | Why |
|---|---|---|---|
| `trivy` | SCA / container | `vuln_ids`, `component_name`, `component_version` | A CVE against a specific package@version is the identity; file/line absent, description volatile |
| `grype` | SCA | `vuln_ids`, `component_name`, `component_version` | Same identity model as Trivy → enables cross-tool dedup with it |
| `kubescape` | K8s posture | `vuln_ids`, `title`, `file_path` | Control id (`C-xxxx`) + control name + manifest path; no package/version |
| `bandit` | SAST | `vuln_ids`, `title`, `file_path`, `cwe` | Rule id + rule + file; **`line` deliberately excluded** so edits above the finding don't move it |
| `sarif` | generic SAST | `vuln_ids`, `title`, `file_path`, `cwe` | Same reasoning as bandit; SARIF is multi-tool |
| `generic` | Kata format | `vuln_ids`, `title`, `file_path`, `component_name` | Caller may set any subset; everything in the key is caller-stable |

`dedup_algorithm` per scanner:
- Tools with a reliable unique id (bandit rule+location id, kubescape control id) →
  `unique_id_from_tool_or_hash_code` (prefer the id, fall back to hash).
- SCA tools (trivy, grype) → `hash_code` (their "unique id" is just the CVE, which repeats
  across packages; the hash is the real key).

**`line` is in no hash.** Including it is the classic DefectDojo churn bug; we denormalize
`line` for display only.

## Consequences

- Each new parser must ship a `scanner_config` row **with a rationale comment** before its
  findings dedup correctly; seeding without thought silently breaks dedup.
- Cross-tool dedup only works between tools whose `hash_fields` share the CVE+component
  subset (trivy↔grype). Kubescape/SAST never cross-dedup — correct, they describe different
  things.
- Changing a scanner's fields does **not** retroactively rehash. A management command
  recomputes hashes with a dry-run diff (Phase 3 Week 1), matching DefectDojo.

## How DefectDojo does it

Same model: `HASHCODE_FIELDS_PER_SCANNER` + `always` fields, four selectable algorithms,
non-retroactive config, a `dedupe` management command. We skip `legacy`. We keep DefectDojo's
hard-won lesson that `line` in the hash causes finding churn, and leave it out from the start.

## Revisit when

A scanner's dedup produces visible duplicates or wrongful "moves" in the parity harness, or
a tool emits a stable unique id we are currently ignoring.
