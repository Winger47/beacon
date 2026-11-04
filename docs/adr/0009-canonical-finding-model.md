# ADR-0009: Canonical finding model and the Location generalization

- Status: accepted
- Date: 2026-11-04

## Context
Every parser (Trivy, Kubescape, the Kata generic format, and the dozen scanners that
arrive in Phase 5) must emit the *same* in-process object so the importer, dedup (Phase 3)
and the reconciler (Phase 4) never special-case a tool. That object is
`kata_parsers.Finding` (a frozen dataclass) and its persisted twin `core.finding`.

The hard part is **location**. Scanners describe *where* a finding lives in wildly different
terms:

- SAST (Semgrep, gosec, Bandit): a file path + line/column.
- Container/OS scanners (Trivy, Grype): an image reference + a package and (sometimes) a
  layer/package path.
- IaC / Kubernetes (Kubescape, kube-bench): a cluster resource — `namespace/kind/name` — and
  sometimes a manifest file.
- Cloud posture (Prowler): a cloud account + region + resource ARN.
- DAST: an endpoint (scheme/host/port/path).

A single pair of `file_path` / `line` columns (DefectDojo's approach) cannot express an image
layer or a k8s resource without abuse. But a fully normalized `Location` table per kind is a
lot of schema for Phase 2, and dedup only needs a handful of these fields as *hash inputs*,
not as queryable relations (yet).

## Options considered
| Option | Pros | Cons |
|---|---|---|
| Flat `file_path`/`line` only (DefectDojo-style) | Simplest; already indexable | Cannot represent image layer, k8s resource, cloud ARN, endpoint without overloading one string |
| One normalized table per location kind | Fully queryable, typed | Heavy schema now; most fields unused until later phases; parser must know table shape |
| **Generalized `location`: a typed JSONB list, plus keep flat `file_path`/`line` as a denormalized convenience** | One shape for every tool; parser stays dumb; dedup reads whatever fields its scanner config names; promote hot fields to columns later | JSONB is not relationally queryable until promoted; needs a documented per-kind key set |

## Decision
`Finding` carries a `locations: tuple[dict[str, object], ...]`. Each dict has a required
discriminator `kind` and a documented, per-kind set of keys:

- `{"kind": "file", "path": str, "line": int | None, "column": int | None}`
- `{"kind": "image", "image": str, "package_path": str | None}`
- `{"kind": "k8s", "cluster": str | None, "namespace": str | None, "resource_kind": str, "name": str}`
- `{"kind": "cloud", "provider": str, "account": str, "region": str | None, "resource": str}`
- `{"kind": "endpoint", "scheme": str, "host": str, "port": int | None, "path": str | None}`

Persistence (`core.finding`):
- `location JSONB` stores the list verbatim (the importer writes `locations` straight through).
- `file_path TEXT` and `line INT` remain as **denormalized convenience columns**, populated
  from the *first* `file`-kind location when one is present. They exist for cheap UI display
  and SAST-style queries without a JSONB extraction; they are never the source of truth.
- The relational `Endpoint` model and per-endpoint status are **deferred to Phase 6** (they are
  listed there in project.md). Until then, endpoints live only inside `location`.

Rules:
1. A parser emits locations faithfully and does **not** merge or dedup them. Whether the same
   CVE in three image layers collapses to one finding is a *dedup/hash* decision (Phase 3,
   `scanner_config.hash_fields`), not a parser decision. (This is the project.md Phase 2
   "think first" answer, recorded here so later parsers follow it.)
2. Unknown/extra tool fields that are not part of a documented kind go in `Finding.extra`
   (a flat `str→str` map), never invented into `location`.
3. Adding a new `kind` is an ADR amendment, not a silent parser change, so hash-field configs
   stay meaningful.

## Consequences
- **Easier:** every parser targets one object; adding a scanner never touches the schema;
  dedup reads exactly the `location` sub-fields its `scanner_config` names.
- **Harder:** `location` is not SQL-queryable by sub-field until a field is promoted to a
  column (we accept this; promote on evidence, like `file_path` already is). The per-kind key
  set is a contract that must be kept in sync between this ADR, the parsers, and the Phase 4
  Protobuf `NormalizedFinding`.
- **Must monitor:** JSONB bloat on findings with many locations; whether a GIN index on
  `location` is ever needed for triage queries.

## How DefectDojo does it
Different. DefectDojo puts `file_path` + `line` directly on `Finding` and models web targets
as a separate `Endpoint` M2M with per-endpoint status; container/k8s/cloud context is squeezed
into free-text fields and tags. Kata generalizes location into one typed JSONB list so
non-file scanners are first-class, and defers the relational `Endpoint` table to Phase 6 where
per-endpoint mitigation is actually built. (Behavioral reference only; no DefectDojo code used.)

## Revisit when
A triage query needs to filter by a `location` sub-field at scale (promote it to a column), or
a scanner needs a location kind not listed here (amend the kind table), or Phase 6 introduces
the relational `Endpoint` model (reconcile `endpoint`-kind locations with it).
