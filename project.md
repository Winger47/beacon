# Kata: A From-Scratch Reimplementation of DefectDojo's Architecture

> In a dojo, a *kata* is the practice form you repeat until the movement becomes yours.
> That is the purpose of this project: rebuild DefectDojo's core from first principles,
> make your own design decisions, then compare them with how DefectDojo actually works.

| Field | Value |
|---|---|
| Status | Planning |
| Stack | Python (core + parsers), Go (ingestion plane + agents), React + TypeScript (web) |
| Constraint | Free and open-source technology only |
| Reference system | OWASP DefectDojo (open-source edition) |
| Primary learning goal | High-volume backend engineering: ingestion, normalization, dedup, idempotency, async pipelines |
| Last updated | 2026-11-03 |

---

## How to read this document

The document is split into two views:

- **Macroscope (Part V):** the whole project as phases. Use it to know *where you are* and *what done looks like* for each phase.
- **Microscope (Part VI):** every phase broken into concrete tasks, acceptance criteria and "think first" questions. Use it for day-to-day work.

Everything before that (Parts I to IV) is the design: requirements, HLD, LLD and the scanner catalogue. Read the design once fully before starting Phase 0, then revisit the relevant LLD section at the start of each phase.

| Part | Content |
|---|---|
| 0 | Ground rules |
| I | Requirements and scale estimation |
| II | High-Level Design (HLD) |
| III | Low-Level Design (LLD) |
| IV | Scanner and integration catalogue |
| V | Macroscope plan (phases) |
| VI | Microscope plan (tasks per phase) |
| VII | Testing strategy |
| VIII | Benchmarks and resume narrative |
| IX | Risks and anti-patterns |
| X | Repository layout |
| Appendix | ADR template, glossary, references |

---

## Part 0: Ground Rules

1. **Clone the design, not the code.** For every feature:
   1. Use the feature in a local DefectDojo install and observe the behavior.
   2. Design your own solution. Write the reasoning down (ADR) *before* coding.
   3. Build it.
   4. Only now read how DefectDojo did it. Record where you differed and why.
   Step 4 is where most of the learning happens, and it is your interview material.
2. **Free and open source only.** Every dependency must be OSI-licensed or free to self-host. Paid SaaS and commercial scanners are excluded. Where a "free tier of a paid API" appears (only in the optional AI module), a self-hosted fallback is mandatory.
3. **Measure everything.** Every phase ends with a test suite or a benchmark. A claim without a number does not go on the resume.
4. **Decisions are written down.** Every non-trivial choice gets an ADR in `docs/adr/` (template in the Appendix).
5. **Scope discipline.** A phase is done when its exit criteria pass, not when it is perfect. Unfinished "nice to haves" go into a backlog, not into the current phase.
6. **Honest positioning.** Describe it as *"a from-scratch reimplementation of DefectDojo's core architecture, with a redesigned streaming ingestion pipeline."* DefectDojo's open-source edition is already free, so "free" is not a differentiator. Your differentiators are the design decisions you made and measured.

---

## Part I: Requirements

### 1.1 Functional requirements (DefectDojo parity map)

Priority: **P0** = core, must exist for the project to make sense. **P1** = parity feature. **P2** = nice to have. **EXT** = Kata extension that DefectDojo does not do (or does differently).

| # | Capability | DefectDojo concept | Priority | Phase |
|---|---|---|---|---|
| F1 | Organizational hierarchy | Product Type → Product → Engagement → Test → Finding | P0 | 1 |
| F2 | Users, global roles, product-level roles | Users, Roles, Product/Product Type members | P0 | 1 |
| F3 | API with token auth for CI | API v2 + API keys | P0 | 1 |
| F4 | Import a scan report into a new Test | Import Scan | P0 | 2 |
| F5 | Reimport into an existing Test (create / untouched / reactivate / close) | Reimport Scan | P0 | 3 |
| F6 | Deduplication: same-tool and cross-tool | 4 dedup algorithms, per-parser config | P0 | 3 |
| F7 | Import history per Test | Test Import history | P0 | 3 |
| F8 | Very large report ingestion (10 GB) without OOM | (DD struggles here, see 1.2) | EXT | 4 |
| F9 | Finding triage: status, verify, false positive, out of scope, notes, files, tags | Finding workflow | P0 | 6 |
| F10 | Endpoints / locations attached to findings | Endpoint, Endpoint Status | P1 | 6 |
| F11 | Components (package + version) and SBOM import | Component | P1 | 5/6 |
| F12 | Risk acceptance with expiry and auto-reactivation | Risk Acceptance | P1 | 6 |
| F13 | SLA configuration per product and breach tracking | SLA Configuration | P1 | 6 |
| F14 | Finding groups | Finding Group | P2 | 6 |
| F15 | Notifications (email, chat, webhook) with per-user subscriptions | Notifications | P1 | 7 |
| F16 | Issue tracker sync (two-way) | JIRA integration | P1 | 7 |
| F17 | Metrics dashboards (open by severity, MTTR, SLA compliance, trends) | Metrics | P1 | 8 |
| F18 | Reports (PDF / CSV) | Reports | P2 | 8 |
| F19 | Audit log of every state change | Audit / history | P1 | 6 |
| F20 | Scan-runner agent that runs scanners in the client environment and pushes reports | (DD only ingests) | EXT | 7 |
| F21 | Generic formats: SARIF, CycloneDX, generic JSON | Generic Findings Import, SARIF parser | P0 | 5 |
| F22 | Live import progress in the UI | (DD shows result after completion) | EXT | 4 |
| F23 | Mass-closure safety guard on reimport | (DD closes whatever is missing) | EXT | 3 |
| F24 | AI-assisted triage and summaries | (not in DD OSS) | EXT, optional | 10 |

### 1.2 Non-functional requirements

| Area | Requirement | Why it matters |
|---|---|---|
| Large input | Import a single 10 GB report with bounded memory per worker (target: under 512 MB RSS regardless of file size) | Production DefectDojo deployments hit OOM on large imports and are tuned by lowering Celery concurrency. This is the core engineering problem Kata solves differently. |
| Throughput | Hypothesis to validate: at least 5,000 normalized findings/sec sustained on an 8 vCPU / 16 GB dev box | Gives you a number to beat and to put on the resume |
| Idempotency | Uploading the same report twice with the same idempotency key creates zero extra findings; retries of any pipeline stage never double-apply | At-least-once delivery is the default everywhere in this design |
| Correctness | A truncated or partially processed report must never mass-close findings | Reimport closes "what is missing"; a half-read file looks like "everything is fixed" |
| API latency | p95 under 300 ms for paginated finding lists at 10M findings | Forces keyset pagination and correct indexes |
| Durability | An upload is acknowledged only after it is durably in object storage | No silent data loss |
| Scalability | All services except PostgreSQL are stateless and horizontally scalable | Standard; makes the scaling story clean |
| Security | RBAC enforced in the data layer on every query; reports are treated as untrusted input; secrets never logged | A security tool that is itself insecure is a bad look in an interview |
| Observability | RED metrics on every service; one distributed trace from upload to final reconcile | You will need this to debug the async pipeline |
| Portability | Runs fully on `docker compose up` on a laptop; deployable to k3s/kind via Helm | Free to run, easy to demo |

### 1.3 Scale estimation (back of the envelope)

These are assumptions to validate with real reports in Phase 4, not facts.

| Quantity | Assumption | Result |
|---|---|---|
| Average serialized finding in a raw JSON report | ~2 KB (descriptions and references dominate) | 10 GB ≈ **5M raw findings** |
| Normalized finding row + indexes in PostgreSQL | ~1.5 KB row + ~1 KB index share | 5M findings ≈ **12.5 GB** in Postgres |
| Import time at 5k findings/sec | | 5M / 5k ≈ **17 minutes** |
| Import time at 50k findings/sec (COPY-based batch writes) | | ≈ **100 seconds** |
| Steady-state daily load | 50 products × 5 scanners × 1 scan/day × 20k findings | **5M finding observations/day ≈ 58/sec average**, bursts ~10× during CI windows |
| Fraction of reimport observations that are "untouched" | 90 to 98% in a mature product | The hot path is **lookup and compare**, not insert |

The last row is the most important insight in the whole design:

> In steady state, almost every incoming finding already exists. The system is
> read-and-compare heavy, not write heavy. Design the reimport path around fast
> set-based key comparison, not around fast inserts.

**Think first:** if 95% of incoming findings are untouched, where should the index be, what should it contain, and is a per-finding `SELECT` ever acceptable on this path?

---

## Part II: High-Level Design

### 2.1 How DefectDojo is built (the reference)

According to its documentation, the open-source DefectDojo is a Python/Django application served by uWSGI behind NGINX, which serves static content. Background work such as deduplication and JIRA synchronization runs in Celery workers, scheduled jobs run in Celery Beat, the broker in the docker compose setup is Valkey, and PostgreSQL is the only supported database. Uploaded media (threat models, risk acceptance files) live in a docker volume.

In short: **a monolith with a task queue.** That is a perfectly good architecture for its workload. Kata keeps the monolith idea for the transactional core and redesigns only the part with a genuinely different scaling profile: ingestion.

### 2.2 ADR-001: Architecture style

| Option | Pros | Cons |
|---|---|---|
| **Monolith + task queue** (DefectDojo) | Simple deploys, one transaction boundary, fast to build | Large imports compete with web traffic for the same workers and DB connections; one bad parser can OOM a shared worker |
| **Modular monolith** | Clear module boundaries, still one deployable | Doesn't isolate ingestion's resource profile |
| **Full microservices** (one service per entity) | Independent deploys | Distributed transactions for triage workflows that are naturally transactional; a "distributed monolith" for a solo developer |
| **Modular monolith core + extracted ingestion plane** (chosen) | Ingestion scales and fails independently; core stays transactional and simple | Two deployment units to reason about; async pipeline needs idempotency and observability work |

**Decision:** Kata is a **modular monolith core (`core-api`) plus an extracted, event-driven ingestion plane** (gateway, parser workers, reconciler), plus a few small edge services (notifier, scheduler, agent).

**Reasoning (the interview answer):** split along *scaling and failure profiles*, not along nouns. Ingestion is bursty, CPU and I/O heavy, handles untrusted multi-GB input, and must not take down triage. Triage CRUD is low-volume and transactional. Splitting "products" and "engagements" into separate services would buy nothing but distributed transactions.

**Anti-pattern to avoid:** building 12 services in Phase 1. Phases 1 to 3 run everything inside `core-api` with a simple in-process import. The ingestion plane is *extracted* in Phase 4, once you understand the domain. That extraction is itself a great interview story.

### 2.3 System context diagram

```
  Users (browser)                       CI pipelines / scan-runner agents
        |                                              |
        v                                              |
+------------------+                                   |
|  web (React SPA) |                                   |
+--------+---------+                                   |
         |                                             |
         v                                             v
+------------------------------------------------------------------+
|              edge proxy (Caddy or NGINX): TLS, routing            |
+-----------+--------------------------------------+---------------+
            | /api/*                               | /ingest/*
            v                                      v
+------------------------+              +--------------------------+
|   core-api (Python)    |              |   ingest-gateway (Go)    |
|  domain, RBAC, triage, |              |  streaming upload,       |
|  queries, outbox       |              |  idempotency, sha256     |
+---+-------------+------+              +-----+---------------+----+
    |             |                           |               |
    |             |                 raw bytes |               | import.requested
    |             |                           v               v
    |             |                 +----------------+   +-----------------------------------+
    |             |                 | object storage |   |            Apache Kafka           |
    |             |                 |  (SeaweedFS)   |   | import.requested                  |
    |             |                 +-------+--------+   | findings.normalized (batches)     |
    |             |                         ^            | import.status                     |
    |             |              stream read|            | domain.events                     |
    |             |                         |            +---+-----------+-----------+-------+
    |             |                +--------+---------+      |           |           |
    |             |                | parser-workers   |<-----+           |           |
    |             |                | (Python)         |----------------->|           |
    |             |                +------------------+  normalized      |           |
    |             |                                      batches         v           v
    |             |                                         +----------------+  +---------------+
    |             |                                         | reconciler     |  | notifier (Go) |
    |             |                                         | dedup+reimport |  | integration-  |
    |             |                                         | (Python -> Go) |  | sync (Python) |
    |             |                                         +-------+--------+  +---------------+
    v             v                                                 v
+------------------------------------------------------------------------------------------+
|                         PostgreSQL (system of record)                                     |
|   schemas: core (domain), ingest (jobs, batches), notify (subscriptions, deliveries)     |
+------------------------------------------------------------------------------------------+
    |
+---+--------------+   +--------------------+   +--------------------+   +----------------+
| Valkey           |   | scheduler (Python) |   | Keycloak (OIDC)    |   | observability  |
| cache, rate      |   | SLA breach, risk   |   | users, SSO         |   | OTel, Prom,    |
| limits, sessions |   | acceptance expiry  |   |                    |   | Grafana, Loki  |
+------------------+   +--------------------+   +--------------------+   +----------------+
```

### 2.4 Services

| Service | Language | Responsibility | Owns data | Scales on | Introduced |
|---|---|---|---|---|---|
| `web` | React + TS | UI | none | static (CDN-able) | Phase 1 |
| `edge` | Caddy / NGINX | TLS, routing, body size limits | none | connections | Phase 0 |
| `core-api` | Python (FastAPI) | Domain model, RBAC, triage workflows, queries, outbox writes | `core` schema | request rate | Phase 1 |
| `ingest-gateway` | Go | Streaming uploads, idempotency, checksums, job creation | `ingest.import_job` | concurrent uploads, bandwidth | Phase 4 |
| `parser-workers` | Python | Stream-parse raw reports into canonical findings, emit batches | none (stateless) | CPU; Kafka partitions | Phase 4 |
| `reconciler` | Python first, hot path ported to Go later | Hashing, dedup, reimport diff, upserts, close-old-findings, job finalization | writes `core.finding*`, `ingest.applied_batch` | Kafka partitions; DB write capacity | Phase 4 |
| `outbox-relay` | Go | Publishes outbox rows to `domain.events` | `core.outbox` (reads) | event rate | Phase 7 |
| `notifier` | Go | Channel delivery (email, chat, webhook), digests, retries | `notify` schema | event rate | Phase 7 |
| `integration-sync` | Python | GitHub/GitLab issue sync, inbound webhooks | `core.finding_issue_link` | low | Phase 7 |
| `scheduler` | Python | SLA breach detection, risk acceptance expiry, scheduled reports | none (uses `core`) | low | Phase 6 |
| `report-worker` | Python | Async PDF / CSV generation | object storage | low | Phase 8 |
| `scan-runner` (agent) | Go | Runs scanners in the client environment, pushes reports via ingest API | local config | per client | Phase 7 |
| `ai-service` (optional) | Python | Summaries, remediation hints, semantic dedup suggestions | `ai` schema | low | Phase 10 |

### 2.5 Core flows

**Flow A: Import (new Test)**

1. Client calls `POST /ingest/v1/uploads` with metadata (target product/engagement, `scan_type`, `mode=import`) and an `Idempotency-Key` header.
2. `ingest-gateway` checks the idempotency key. If the key was seen for this principal, it returns the existing job. Otherwise it creates `import_job` in state `RECEIVING`.
3. The gateway streams the request body to object storage via multipart upload, computing SHA-256 on the fly. It never buffers the whole file in memory.
4. On successful upload: job → `QUEUED`, and an `import.requested` event is written (via the gateway's own outbox row, published by the relay).
5. A `parser-worker` consumes the event, stream-reads the object, and emits `FindingBatch` messages (e.g. 500 findings each, zstd-compressed) to `findings.normalized`, keyed by `product_id`. The final batch carries `last=true` and the total count.
6. The `reconciler` consumes batches in order per key, computes hashes, runs dedup, and applies changes with set-based SQL. Each `(job_id, seq)` is recorded in `ingest.applied_batch`, so replays are no-ops.
7. When all batches up to `last` are applied, the reconciler finalizes: writes the `test_import` record with counts, emits domain events via the outbox, and marks the job `COMPLETED`.
8. The UI receives progress via Server-Sent Events from `core-api`, which reads job state and `import.status` events.

**Flow B: Reimport (existing Test)**

Same as Flow A up to step 6, with `mode=reimport`. The reconciler stages incoming match keys and computes the diff against the Test's existing findings: **create / untouched / reactivate / close**. Closing happens only during finalization, after every batch is confirmed. Full algorithm in LLD 3.7.

**Flow C: Agent scan**

The `scan-runner` agent (in CI or as a Kubernetes CronJob) runs e.g. Trivy and Kubescape locally, then uploads results through Flow A or B using a scoped API token. Kata never needs credentials to the client's environment (push model; see LLD 3.14).

**Flow D: Triage**

UI → `core-api` → single PostgreSQL transaction (finding update + audit log row + outbox row) → outbox relay → `domain.events` → notifier / integration-sync.

### 2.6 Technology choices and licenses

Licenses change. Re-check each before adopting it, and record the check in the ADR.

| Concern | Choice | License | Rejected alternatives and why |
|---|---|---|---|
| Core API | FastAPI + SQLAlchemy 2.x + Alembic + Pydantic v2 | MIT | **Django + DRF** (DefectDojo's choice): faster CRUD and a free admin, but the ORM hides the SQL you are trying to learn, and you already know Django. Pick Django if speed of delivery matters more than learning. |
| Ingest gateway | Go standard library `net/http` + `chi` router | BSD / MIT | Python: workable, but streaming many concurrent multi-GB uploads is where Go's goroutines and low per-connection memory shine |
| Parser workers | Python + `ijson` (streaming JSON) + `lxml.etree.iterparse` / `defusedxml` (streaming, safe XML) | BSD | Go parsers: faster, but most scanner ecosystems and reference parsers are Python. Port only the hottest parser to Go later and benchmark it. |
| Message bus | Apache Kafka (KRaft mode, no ZooKeeper) | Apache-2.0 | **NATS JetStream** (Apache-2.0): lighter, simpler, a valid choice. **RabbitMQ** (MPL-2.0): great for task queues, weaker for partition-ordered replayable logs. **Valkey Streams**: simple but weaker tooling. Redpanda is excluded (source-available, not OSI). Kafka wins on learning value: partitions, consumer groups, ordering, replay, lag. |
| Primary DB | PostgreSQL 16+ | PostgreSQL License | **MongoDB**: findings are highly relational (hierarchy, joins, M2M with endpoints and risk acceptances) and need transactional updates with audit and outbox rows. Mongo's server license is also SSPL, not OSI. |
| Cache, rate limits | Valkey | BSD-3 | Redis moved away from its BSD license in 2024; Valkey is the BSD fork (and what DefectDojo uses now) |
| Object storage | SeaweedFS (S3 API); local filesystem adapter for dev | Apache-2.0 | **MinIO**: its community edition went into maintenance mode in late 2025 and its repository has since been archived. **Garage**: AGPL, minimal, good for tiny clusters. **RustFS**: Apache-2.0, younger. |
| Search (optional) | OpenSearch | Apache-2.0 | Postgres full-text search first; add OpenSearch only if measured need |
| Analytics (optional) | ClickHouse | Apache-2.0 | Postgres materialized views first |
| Identity | Keycloak (OIDC) | Apache-2.0 | Hand-rolled JWT auth: good learning, but then you own password storage and MFA. Use Keycloak for users; build API tokens yourself. |
| Frontend | React + TypeScript + Vite, TanStack Query, TanStack Table + TanStack Virtual, React Router, Apache ECharts, shadcn/ui or Mantine | MIT / Apache-2.0 | Next.js: SSR is unnecessary for an authenticated dashboard |
| Contracts | Protocol Buffers + Buf CLI (breaking-change checks) | Apache-2.0 | JSON Schema: simpler but no codegen for Go and Python from one source, weaker compatibility tooling |
| Observability | OpenTelemetry SDKs + Collector, Prometheus, Grafana, Loki, Tempo (or Jaeger) | Apache-2.0 / AGPL-3.0 | AGPL is fine for self-hosting; you are not modifying and distributing them |
| Load testing | k6 or Locust | AGPL-3.0 / MIT | |
| Testing | pytest, Hypothesis, testcontainers, Go `testing`, Playwright | MIT / MPL / Apache-2.0 | |
| Deploy | Docker Compose → kind or k3s + Helm; Argo CD optional | Apache-2.0 | |
| PDF reports | WeasyPrint | BSD | |
| Vector search (optional AI) | pgvector | PostgreSQL License | Separate vector DB: unnecessary at this scale |
| LLM (optional AI) | Ollama (self-hosted, default); OpenRouter / Groq free tiers optional | MIT / proprietary free tiers | Free tiers have rate limits and terms that can change; never make them a hard dependency |

### 2.7 Data ownership

One PostgreSQL cluster with **separate schemas** and a strict rule: *a service writes only to its own schema; cross-schema reads go through views or APIs.*

| Schema | Owner | Contents |
|---|---|---|
| `core` | `core-api` (reconciler writes findings through a well-defined repository module shared via a library) | Product hierarchy, findings, endpoints, components, risk acceptances, SLA, audit log, outbox |
| `ingest` | `ingest-gateway` + `reconciler` | Import jobs, applied batches, staging tables |
| `notify` | `notifier` | Subscriptions, deliveries, digests |

**Tradeoff:** database-per-service gives stronger isolation but makes the reconciler's "dedup + upsert + audit + outbox in one transaction" impossible without sagas. One cluster with schema ownership keeps transactions local where correctness needs them. Revisit only if a measured bottleneck appears.

The reconciler writing to `core.finding` is a deliberate, documented exception: it is the "write side" of the findings aggregate. Put that write logic in one shared package (`kata-domain`) so the rules live in exactly one place.

### 2.8 Multi-tenancy and authorization

DefectDojo's model: global roles, plus role memberships at the Product Type and Product level. Kata copies this.

- **Roles:** Reader, API Importer, Writer, Maintainer, Owner (verify the exact permission matrix against DefectDojo's docs while building).
- **Enforcement point:** every finding query joins against an authorized-products set, so RBAC lives in the data layer, not in UI code.
- **Implementation:** a table `core.user_product_access(user_id, product_id, role)` maintained on membership changes (direct and via product type), cached in Valkey with explicit invalidation.

| Option | Pros | Cons |
|---|---|---|
| Application-layer filter (chosen) | Explicit, testable, easy to debug | Every new query must remember the filter. Mitigate with a single query builder that always applies it, plus tests that fail on unscoped queries. |
| PostgreSQL Row-Level Security | Enforced by the DB even for buggy code | Session variables per request, harder debugging, pooling caveats |

**Think first:** a user is removed from a product. Their cached access set still says "allowed" for up to the TTL. What is your acceptable staleness window, and how do you make revocation immediate?

### 2.9 Failure modes

| Failure | Effect | Mitigation |
|---|---|---|
| Object storage unavailable | Uploads cannot be persisted | Gateway returns `503` with `Retry-After`; never acknowledges an upload that is not durable |
| Kafka unavailable | Jobs cannot be queued | Gateway writes `import_job` + an outbox row in one DB transaction; the relay publishes when Kafka returns. The upload is still acknowledged as `QUEUED_PENDING`. |
| Parser worker crashes mid-file (OOM, bug, malformed input) | Partial batches emitted | At-least-once: the job is reprocessed from the start; the reconciler ignores already-applied `(job_id, seq)`. After N attempts, the message goes to a DLQ and the job is `FAILED` with a reason. |
| Malicious or malformed report (XXE, zip bomb, deeply nested JSON) | Worker compromise or resource exhaustion | `defusedxml`, max nesting depth, max decompressed size ratio, per-finding size cap, workers run as non-root, read-only FS, no egress except Kafka + object store |
| Reconciler crash between batches | Partially applied import | Batches are idempotent; finalization (close-old-findings) runs only when all batches up to `last` are applied |
| PostgreSQL down or slow | Reconciler cannot write | Consumer pauses (backpressure); Kafka retains messages; lag alert fires |
| Valkey down | Cache and rate limits unavailable | Fall back to PostgreSQL for authz; fail open or closed on rate limits by explicit config. **Never** use Valkey for correctness-critical locks; use PostgreSQL advisory locks. |
| Keycloak down | No new logins | Existing JWTs remain valid until expiry; JWKS is cached |
| Notification channel down (SMTP, chat webhook) | Delayed notifications | Retries with exponential backoff and jitter, DLQ; never blocks imports or triage |
| Two reimports into the same Test at once | Interleaved diffs corrupt state | Finalization takes `pg_advisory_xact_lock(test_id)`; Kafka keying keeps a product's batches ordered |
| Truncated report on reimport | Mass closure of real findings | Close only after full confirmation; plus a **mass-closure circuit breaker** (LLD 3.7) |

**Delivery semantics:** everything is at-least-once. Effectively-once behavior comes from idempotent consumers (`applied_batch` table, idempotency keys, upserts by natural key). Do not try to build exactly-once delivery.

**CAP view:** PostgreSQL single-primary is the consistent system of record (CP). Read replicas and analytics projections are eventually consistent. The pipeline is asynchronous, so the UI must show import status explicitly instead of pretending imports are instant.

### 2.10 Observability

**Metrics (Prometheus):**

| Metric | Type | Labels | Why |
|---|---|---|---|
| `ingest_upload_bytes_total` | counter | scan_type | Bandwidth |
| `ingest_upload_duration_seconds` | histogram | scan_type | Upload latency |
| `parser_findings_emitted_total` | counter | scan_type | Throughput |
| `parser_process_rss_bytes` | gauge | worker | Proves bounded memory |
| `reconciler_batch_apply_seconds` | histogram | mode | DB write performance |
| `kafka_consumer_group_lag` | gauge | group, topic | Backpressure signal |
| `import_job_e2e_seconds` | histogram | scan_type, mode, size_bucket | The headline SLO |
| `dedup_match_ratio` | histogram | scan_type | Sanity check on dedup config |
| `reimport_outcome_total` | counter | outcome (created, untouched, reactivated, closed) | Detects mass-closure anomalies |
| HTTP RED metrics | standard | route, status | API health |

**Tracing:** propagate W3C `traceparent` through HTTP *and* Kafka message headers, so one trace spans upload → parse → reconcile → finalize.

**Logging:** structured JSON with `job_id`, `test_id`, `product_id`, `trace_id`. Never log report contents: scanner output can contain secrets (that is literally what secret scanners find).

**SLOs (initial):**
- 99% of imports under 100 MB complete within 2 minutes.
- 99% of imports under 1 GB complete within 10 minutes.
- API list endpoints p95 under 300 ms.

### 2.11 Deployment and safe change

- **Local:** `docker compose` with profiles (`core`, `ingest`, `observability`, `full`).
- **Demo:** single VM running k3s, installed via a Helm chart from this repo.
- **Migrations:** expand → migrate → contract. Never drop or rename a column in the same release that stops using it.
- **Feature flags:** a simple DB-backed flag table (or OpenFeature with flagd) to roll out the ingestion plane alongside the old in-process import, compare outputs, then switch over. This is a real-world migration pattern and a good interview story.
- **Rollouts:** Kubernetes rolling updates with readiness probes. Consumers must handle `SIGTERM` gracefully: finish the current batch, commit offsets, exit.

---

## Part III: Low-Level Design

### 3.1 Domain model

```
product_type 1──* product 1──* engagement 1──* test 1──* finding
                     │                          │          │
                     │                          │          ├──* finding_note
                     │                          │          ├──* finding_file
                     │                          │          ├──* finding_endpoint_status *──1 endpoint
                     │                          │          ├──1 component (optional)
                     │                          │          ├──* risk_acceptance_finding *──1 risk_acceptance
                     │                          │          └──1 finding (duplicate_of, self reference)
                     │                          └──* test_import (import history)
                     ├──1 sla_configuration
                     └──* product_member (user, role)

test ──1 scanner_config (dedup algorithm, hash fields, reimport rules)
```

**Where Kata deliberately diverges from DefectDojo:** DefectDojo models finding state with several independent booleans (`active`, `verified`, `false_p`, `out_of_scope`, `risk_accepted`, `is_mitigated`, `duplicate`, ...). That allows invalid combinations and makes reimport logic complicated. Kata uses a **single `status` enum** plus a `verified` flag and a `duplicate_of` reference. Write an ADR on this: what you gain (invalid states become unrepresentable), and what you lose (DefectDojo can express "false positive *and* mitigated"; decide whether you need that).

### 3.2 PostgreSQL schema (core tables)

```sql
CREATE SCHEMA core;

CREATE TYPE core.severity AS ENUM ('info', 'low', 'medium', 'high', 'critical');

CREATE TYPE core.finding_status AS ENUM (
  'active',          -- open, needs action
  'mitigated',       -- fixed (closed by reimport or by a human)
  'false_positive',  -- human triage decision
  'out_of_scope',    -- human triage decision
  'risk_accepted',   -- linked to a risk_acceptance with expiry
  'under_review'     -- optional review workflow
);

CREATE TABLE core.sla_configuration (
  id            BIGSERIAL PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  critical_days INT  NOT NULL CHECK (critical_days > 0),
  high_days     INT  NOT NULL CHECK (high_days > 0),
  medium_days   INT  NOT NULL CHECK (medium_days > 0),
  low_days      INT  NOT NULL CHECK (low_days > 0)
);

CREATE TABLE core.product_type (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.product (
  id                   BIGSERIAL PRIMARY KEY,
  product_type_id      BIGINT NOT NULL REFERENCES core.product_type(id),
  name                 TEXT   NOT NULL,
  description          TEXT,
  business_criticality TEXT CHECK (business_criticality IN ('very_high','high','medium','low','very_low')),
  sla_configuration_id BIGINT REFERENCES core.sla_configuration(id),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (product_type_id, name)
);

CREATE TABLE core.engagement (
  id                          BIGSERIAL PRIMARY KEY,
  product_id                  BIGINT NOT NULL REFERENCES core.product(id),
  name                        TEXT   NOT NULL,
  engagement_type             TEXT   NOT NULL CHECK (engagement_type IN ('interactive','ci_cd')),
  status                      TEXT   NOT NULL DEFAULT 'in_progress'
                              CHECK (status IN ('not_started','in_progress','completed')),
  deduplication_on_engagement BOOLEAN NOT NULL DEFAULT false,
  target_start                DATE,
  target_end                  DATE,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.scanner_config (
  scanner_key              TEXT PRIMARY KEY,           -- 'trivy', 'kubescape', 'sarif', ...
  display_name             TEXT NOT NULL,
  dedup_algorithm          TEXT NOT NULL CHECK (dedup_algorithm IN
                           ('unique_id_from_tool','hash_code','unique_id_from_tool_or_hash_code')),
  hash_fields              TEXT[] NOT NULL,            -- e.g. {title, severity, component_name, component_version}
  reimport_algorithm       TEXT NOT NULL,
  reimport_hash_fields     TEXT[] NOT NULL,
  static_tool              BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE core.test (
  id            BIGSERIAL PRIMARY KEY,
  engagement_id BIGINT NOT NULL REFERENCES core.engagement(id),
  scanner_key   TEXT   NOT NULL REFERENCES core.scanner_config(scanner_key),
  title         TEXT,
  service       TEXT,                                   -- optional; participates in hashing if configured
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.component (
  id      BIGSERIAL PRIMARY KEY,
  name    TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT '',
  purl    TEXT,
  UNIQUE (name, version)
);

CREATE TABLE core.finding (
  id                  BIGSERIAL PRIMARY KEY,
  test_id             BIGINT NOT NULL REFERENCES core.test(id),
  engagement_id       BIGINT NOT NULL,                  -- denormalized: dedup scope and authz
  product_id          BIGINT NOT NULL,                  -- denormalized: dedup scope and authz
  title               TEXT   NOT NULL,
  severity            core.severity NOT NULL,
  status              core.finding_status NOT NULL DEFAULT 'active',
  verified            BOOLEAN NOT NULL DEFAULT false,
  description         TEXT,
  mitigation          TEXT,
  impact              TEXT,
  references_text     TEXT,
  cwe                 INT,
  vuln_ids            TEXT[] NOT NULL DEFAULT '{}',    -- CVE-..., GHSA-...
  cvss_v3_vector      TEXT,
  cvss_v3_score       NUMERIC(3,1),
  epss_score          NUMERIC(6,5),
  component_id        BIGINT REFERENCES core.component(id),
  file_path           TEXT,
  line                INT,
  location            JSONB,                            -- generalized location (k8s/cloud/image), see 3.3
  unique_id_from_tool TEXT,
  vuln_id_from_tool   TEXT,
  hash_code           CHAR(64),                         -- sha256 hex
  duplicate_of        BIGINT REFERENCES core.finding(id),
  sla_due_date        DATE,
  first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  mitigated_at        TIMESTAMPTZ,
  raw_ref             TEXT,                             -- object key + byte offset, for "show raw"
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (duplicate_of IS NULL OR duplicate_of <> id),
  CHECK ((status = 'mitigated') = (mitigated_at IS NOT NULL))
);

-- Reimport matching (scoped to one test): the hottest path in the system
CREATE INDEX finding_test_hash      ON core.finding (test_id, hash_code);
CREATE INDEX finding_test_uid       ON core.finding (test_id, unique_id_from_tool)
  WHERE unique_id_from_tool IS NOT NULL;

-- Same-tool and cross-tool dedup (scoped to product); only originals are match targets
CREATE INDEX finding_product_hash   ON core.finding (product_id, hash_code)
  WHERE duplicate_of IS NULL;

-- UI list queries and keyset pagination
CREATE INDEX finding_product_status ON core.finding (product_id, status, severity, id);

-- SLA scheduler
CREATE INDEX finding_sla_due        ON core.finding (sla_due_date) WHERE status = 'active';

-- "Which findings have CVE-X?"
CREATE INDEX finding_vuln_ids_gin   ON core.finding USING GIN (vuln_ids);

CREATE TABLE core.test_import (
  id                BIGSERIAL PRIMARY KEY,
  test_id           BIGINT NOT NULL REFERENCES core.test(id),
  import_job_id     UUID   NOT NULL,
  kind              TEXT   NOT NULL CHECK (kind IN ('import','reimport')),
  created_count     INT NOT NULL DEFAULT 0,
  untouched_count   INT NOT NULL DEFAULT 0,
  reactivated_count INT NOT NULL DEFAULT 0,
  closed_count      INT NOT NULL DEFAULT 0,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.endpoint (
  id         BIGSERIAL PRIMARY KEY,
  product_id BIGINT NOT NULL REFERENCES core.product(id),
  protocol   TEXT, host TEXT NOT NULL, port INT, path TEXT,
  UNIQUE (product_id, protocol, host, port, path)
);

CREATE TABLE core.finding_endpoint_status (
  finding_id   BIGINT NOT NULL REFERENCES core.finding(id) ON DELETE CASCADE,
  endpoint_id  BIGINT NOT NULL REFERENCES core.endpoint(id),
  mitigated    BOOLEAN NOT NULL DEFAULT false,
  mitigated_at TIMESTAMPTZ,
  PRIMARY KEY (finding_id, endpoint_id)
);

CREATE TABLE core.risk_acceptance (
  id                   BIGSERIAL PRIMARY KEY,
  product_id           BIGINT NOT NULL REFERENCES core.product(id),
  owner_user_id        BIGINT NOT NULL,
  reason               TEXT   NOT NULL,
  expiration_date      DATE,
  reactivate_on_expiry BOOLEAN NOT NULL DEFAULT true,
  restart_sla_on_expiry BOOLEAN NOT NULL DEFAULT false,
  expired_at           TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.risk_acceptance_finding (
  risk_acceptance_id BIGINT NOT NULL REFERENCES core.risk_acceptance(id) ON DELETE CASCADE,
  finding_id         BIGINT NOT NULL REFERENCES core.finding(id) ON DELETE CASCADE,
  PRIMARY KEY (risk_acceptance_id, finding_id)
);

-- Append-only audit log, partitioned by month
CREATE TABLE core.audit_log (
  id          BIGSERIAL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor_type  TEXT NOT NULL CHECK (actor_type IN ('user','system','import')),
  actor_id    TEXT NOT NULL,
  entity      TEXT NOT NULL,
  entity_id   BIGINT NOT NULL,
  action      TEXT NOT NULL,
  diff        JSONB,
  PRIMARY KEY (id, occurred_at)
) PARTITION BY RANGE (occurred_at);

-- Transactional outbox
CREATE TABLE core.outbox (
  id           BIGSERIAL PRIMARY KEY,
  event_type   TEXT  NOT NULL,
  aggregate_id TEXT  NOT NULL,       -- used as Kafka key for per-aggregate ordering
  payload      JSONB NOT NULL,
  headers      JSONB NOT NULL DEFAULT '{}',   -- traceparent, etc.
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  published_at TIMESTAMPTZ
);
CREATE INDEX outbox_unpublished ON core.outbox (id) WHERE published_at IS NULL;
```

**Ingestion schema:**

```sql
CREATE SCHEMA ingest;

CREATE TABLE ingest.import_job (
  id               UUID PRIMARY KEY,
  principal_id     TEXT NOT NULL,
  idempotency_key  TEXT NOT NULL,
  mode             TEXT NOT NULL CHECK (mode IN ('import','reimport')),
  scanner_key      TEXT NOT NULL,
  target_test_id   BIGINT,               -- reimport
  target_engagement_id BIGINT,           -- import
  object_key       TEXT,
  size_bytes       BIGINT,
  sha256           CHAR(64),
  options          JSONB NOT NULL DEFAULT '{}',  -- close_old_findings, do_not_reactivate, ...
  state            TEXT NOT NULL,
  attempts         INT  NOT NULL DEFAULT 0,
  total_batches    INT,                  -- known once the parser emits last=true
  applied_batches  INT  NOT NULL DEFAULT 0,
  error            TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (principal_id, idempotency_key)
);

CREATE TABLE ingest.applied_batch (
  job_id     UUID   NOT NULL REFERENCES ingest.import_job(id),
  seq        BIGINT NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (job_id, seq)
);

-- Per-job staging of incoming match keys for set-based reimport diffs (see 3.7)
CREATE UNLOGGED TABLE ingest.reimport_seen (
  job_id    UUID NOT NULL,
  match_key TEXT NOT NULL,
  PRIMARY KEY (job_id, match_key)
);
```

**Partitioning the `finding` table:** don't do it on day one. At 10 to 50M rows with the indexes above, a single table is fine. If Phase 4 benchmarks show index bloat or vacuum trouble, evaluate hash partitioning by `product_id`. Write down the trigger condition in an ADR now ("partition when X"), so the decision is driven by data later.

**Think first:** `UNLOGGED` tables are not crash-safe and are not replicated. Why is that acceptable for `reimport_seen` but would be a disaster for `applied_batch`?

### 3.3 Canonical finding contract (Protocol Buffers)

This is the contract between parser workers and the reconciler. It is the most important interface in the system. Every new scanner is "just" a mapping into this shape.

```proto
syntax = "proto3";
package kata.ingest.v1;

enum Severity {
  SEVERITY_UNSPECIFIED = 0;
  SEVERITY_INFO = 1;
  SEVERITY_LOW = 2;
  SEVERITY_MEDIUM = 3;
  SEVERITY_HIGH = 4;
  SEVERITY_CRITICAL = 5;
}

message Component {
  string name = 1;
  string version = 2;
  string purl = 3;
}

message EndpointLocation  { string protocol = 1; string host = 2; int32 port = 3; string path = 4; }
message FileLocation      { string path = 1; int32 line = 2; }
message ImageLocation     { string image = 1; string digest = 2; string package_path = 3; }
message K8sLocation       { string cluster = 1; string namespace = 2; string kind = 3; string name = 4; string container = 5; }
message CloudLocation     { string provider = 1; string account = 2; string region = 3; string resource_id = 4; string service = 5; }

message Location {
  oneof kind {
    EndpointLocation endpoint = 1;
    FileLocation file = 2;
    ImageLocation image = 3;
    K8sLocation k8s = 4;
    CloudLocation cloud = 5;
  }
}

message NormalizedFinding {
  string title = 1;
  Severity severity = 2;
  string description = 3;
  string mitigation = 4;
  string references = 5;
  repeated string vuln_ids = 6;          // CVE-..., GHSA-...
  optional int32 cwe = 7;
  string cvss_v3_vector = 8;
  optional double cvss_v3_score = 9;
  string unique_id_from_tool = 10;
  string vuln_id_from_tool = 11;         // scanner rule ID, e.g. Kubescape control C-0017
  Component component = 12;
  repeated Location locations = 13;
  map<string, string> extra = 14;        // scanner-specific fields that don't map
  string raw_ref = 15;                   // object key + byte offset of the raw record
}

message FindingBatch {
  string job_id = 1;
  int64 seq = 2;                         // 0..N, contiguous
  bool last = 3;                         // true on the final batch
  int64 cumulative_count = 4;            // findings emitted including this batch
  repeated NormalizedFinding findings = 5;
}
```

Design notes:

- **`Location` is a generalization.** DefectDojo is centered on network `Endpoint`s plus file path/line. Kata adds image, Kubernetes and cloud locations because Kubescape, Trivy and Prowler findings are about *resources*, not URLs. This mirrors ideas from OCSF; read the OCSF Vulnerability Finding and Compliance Finding classes for inspiration.
- **Batch sizing:** Kafka's default maximum message size is about 1 MB. 500 findings × ~1.5 KB = ~750 KB before compression. Use zstd compression on the producer and keep batches around 500 findings. Measure and tune; record the result.
- **Schema evolution:** only add fields, never renumber. Run `buf breaking` in CI.

### 3.4 Parser SDK (Python)

**Rules for every parser:**
1. Input is untrusted. Never `json.load()` or `read()` the whole file. Stream it.
2. A parser maps raw records to `NormalizedFinding`s and does nothing else: no DB access, no dedup, no network.
3. A parser is a generator. Memory must stay flat as input size grows.
4. Every parser ships with golden-file tests (sample report in, expected findings out).

```python
# kata_parsers/base.py
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import BinaryIO, Iterator, ClassVar

logger = logging.getLogger(__name__)


class Severity(IntEnum):
    INFO = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    CRITICAL = 5

    @classmethod
    def from_text(cls, value: str | None) -> "Severity":
        mapping = {
            "critical": cls.CRITICAL, "high": cls.HIGH, "medium": cls.MEDIUM,
            "moderate": cls.MEDIUM, "low": cls.LOW, "info": cls.INFO,
            "informational": cls.INFO, "unknown": cls.INFO, "negligible": cls.INFO,
        }
        if value is None:
            return cls.INFO
        return mapping.get(value.strip().lower(), cls.INFO)


@dataclass(frozen=True, slots=True)
class Finding:
    title: str
    severity: Severity
    description: str = ""
    mitigation: str = ""
    references: str = ""
    vuln_ids: tuple[str, ...] = ()
    cwe: int | None = None
    cvss_v3_vector: str = ""
    cvss_v3_score: float | None = None
    unique_id_from_tool: str = ""
    vuln_id_from_tool: str = ""
    component_name: str = ""
    component_version: str = ""
    locations: tuple[dict, ...] = ()
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParserLimits:
    max_finding_bytes: int = 256 * 1024         # truncate absurd descriptions
    max_findings: int = 50_000_000              # hard stop for runaway input
    max_json_depth: int = 64


class ParserError(Exception):
    """Raised for malformed input. Message must be safe to show to users (no raw content)."""


class ScannerParser(ABC):
    scanner_key: ClassVar[str]
    supported_formats: ClassVar[tuple[str, ...]] = ("json",)

    def __init__(self, limits: ParserLimits | None = None) -> None:
        self.limits = limits or ParserLimits()

    @abstractmethod
    def sniff(self, head: bytes) -> bool:
        """Cheap format detection from the first few KB."""

    @abstractmethod
    def parse(self, stream: BinaryIO) -> Iterator[Finding]:
        """Yield findings one by one. Must not hold the whole report in memory."""


# kata_parsers/registry.py
_REGISTRY: dict[str, type[ScannerParser]] = {}


def register(parser_cls: type[ScannerParser]) -> type[ScannerParser]:
    key = parser_cls.scanner_key
    if key in _REGISTRY:
        raise RuntimeError(f"duplicate parser registration: {key}")
    _REGISTRY[key] = parser_cls
    return parser_cls


def get_parser(scanner_key: str) -> ScannerParser:
    try:
        return _REGISTRY[scanner_key]()
    except KeyError:
        raise ParserError(f"unsupported scanner: {scanner_key}") from None
```

**Example: streaming Trivy parser.** Trivy's JSON report has a top-level `Results` array; each result has a `Target` and arrays such as `Vulnerabilities` and `Misconfigurations`. A single `Results` entry for a big image can itself be huge, so streaming at the `Results.item` level is not enough. Use `ijson`'s event stream and track context.

```python
# kata_parsers/trivy.py
from typing import BinaryIO, Iterator
import ijson

from .base import Finding, ParserError, ScannerParser, Severity
from .registry import register


@register
class TrivyParser(ScannerParser):
    scanner_key = "trivy"

    def sniff(self, head: bytes) -> bool:
        return b'"SchemaVersion"' in head and b'"Results"' in head

    VULN_PREFIX = "Results.item.Vulnerabilities.item"

    def parse(self, stream: BinaryIO) -> Iterator[Finding]:
        target = ""
        builder: ijson.ObjectBuilder | None = None
        emitted = 0
        try:
            for prefix, event, value in ijson.parse(stream):
                if builder is not None:
                    # Inside one vulnerability object: feed events until its own end_map.
                    builder.event(event, value)
                    if prefix == self.VULN_PREFIX and event == "end_map":
                        yield self._map_vuln(target, builder.value)
                        builder = None
                        emitted += 1
                        if emitted >= self.limits.max_findings:
                            raise ParserError("report exceeds max_findings limit")
                    continue

                if prefix == "Results.item.Target" and event == "string":
                    target = value
                elif prefix == self.VULN_PREFIX and event == "start_map":
                    builder = ijson.ObjectBuilder()
                    builder.event(event, value)
        except ijson.JSONError as exc:
            raise ParserError(f"malformed Trivy JSON: {type(exc).__name__}") from None
```

Nested objects inside a vulnerability (for example its CVSS map) emit `end_map` events with a *longer* prefix, so only the vulnerability's own closing brace matches `VULN_PREFIX` exactly. Note that `ijson` yields numbers as `Decimal`; convert explicitly in the mapper. Misconfigurations (`Results.item.Misconfigurations.item`) follow the same pattern. Two approaches to compare and benchmark:

| Approach | How | Tradeoff |
|---|---|---|
| `ijson.items(stream, "Results.item")` | Yields one full Result (with all its vulnerabilities) at a time | Simple; memory bounded by the *largest single Result*, not the file. Often good enough. Measure it. |
| Event loop with `ijson.parse` + `ObjectBuilder` per vulnerability | Track `Target` from events, build one vulnerability at a time | Truly flat memory; more complex. Relies on `Target` appearing before `Vulnerabilities` inside each Result. |

**Important subtlety:** JSON objects are unordered by specification. Trivy's Go encoder emits struct fields in declaration order, so `Target` appears before `Vulnerabilities` in practice, but that is an implementation detail. If you rely on it, document the assumption and add a test that fails loudly if a Trivy upgrade changes it. This is exactly the kind of hidden assumption interviewers like to probe.

Mapping one Trivy vulnerability into the canonical model:

```python
def _map_vuln(self, target: str, v: dict) -> Finding:
    vuln_id = v.get("VulnerabilityID", "")
    pkg = v.get("PkgName", "")
    installed = v.get("InstalledVersion", "")
    fixed = v.get("FixedVersion", "")
    title = f"{vuln_id} {pkg} {installed}".strip()
    mitigation = f"Upgrade {pkg} to {fixed}" if fixed else "No fixed version available"
    return Finding(
        title=title[:500],
        severity=Severity.from_text(v.get("Severity")),
        description=(v.get("Description") or "")[: self.limits.max_finding_bytes],
        mitigation=mitigation,
        references=v.get("PrimaryURL", ""),
        vuln_ids=(vuln_id,) if vuln_id else (),
        cwe=_first_cwe(v.get("CweIDs")),
        vuln_id_from_tool=vuln_id,
        component_name=pkg,
        component_version=installed,
        locations=({"kind": "image", "image": target, "package_path": v.get("PkgPath", "")},),
    )
```

Verify every field name against a real Trivy report generated by the version you install. Do not trust this snippet (or any blog post) over a real sample file.

### 3.5 Ingest gateway (Go)

**Upload protocol options:**

| Option | How | Pros | Cons |
|---|---|---|---|
| Single streaming `PUT`/`POST` | Body streamed straight to object storage | Simplest; fine up to a few GB on good networks | A dropped connection at 9.5 GB restarts from zero |
| Chunked / resumable upload (chosen for large files) | Client uploads fixed-size parts; gateway maps them to S3 multipart parts | Resumable; parallel parts | More protocol surface; part tracking |
| tus protocol (`tusd`, MIT) | Open resumable upload standard | Battle-tested, client libraries exist | Another component; less to learn by building |

Start with **single streaming upload** (Phase 4a), add **resumable multipart** (Phase 4b) once the pipeline works. Measure where single upload breaks.

**Streaming handler sketch:**

```go
// ingest-gateway/internal/upload/handler.go
package upload

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"log/slog"
	"net/http"
)

const maxUploadBytes = 20 << 30 // 20 GiB hard cap

type Store interface {
	// PutStream streams r into object storage under key and returns bytes written.
	PutStream(ctx context.Context, key string, r io.Reader) (int64, error)
}

type Jobs interface {
	CreateOrGet(ctx context.Context, principal, idemKey string, meta JobMeta) (job Job, created bool, err error)
	MarkQueued(ctx context.Context, jobID string, objectKey string, size int64, sha string) error
	MarkFailed(ctx context.Context, jobID string, reason string) error
}

type Handler struct {
	store Store
	jobs  Jobs
	log   *slog.Logger
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	principal := PrincipalFrom(ctx)          // set by auth middleware
	idemKey := r.Header.Get("Idempotency-Key")
	if idemKey == "" {
		http.Error(w, "Idempotency-Key header required", http.StatusBadRequest)
		return
	}

	meta, err := ParseMeta(r) // scanner_key, mode, target ids, options (query params or headers)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	job, created, err := h.jobs.CreateOrGet(ctx, principal, idemKey, meta)
	if err != nil {
		h.log.ErrorContext(ctx, "create job", "err", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	if !created {
		writeJSON(w, http.StatusOK, job) // idempotent replay: same job, no new upload
		return
	}

	body := http.MaxBytesReader(w, r.Body, maxUploadBytes)
	hasher := sha256.New()
	tee := io.TeeReader(body, hasher) // hash while streaming, never buffer the file

	objectKey := "raw/" + job.ID
	size, err := h.store.PutStream(ctx, objectKey, tee)
	if err != nil {
		var tooLarge *http.MaxBytesError
		reason := "upload failed"
		status := http.StatusServiceUnavailable
		if errors.As(err, &tooLarge) {
			reason, status = "file too large", http.StatusRequestEntityTooLarge
		}
		_ = h.jobs.MarkFailed(ctx, job.ID, reason)
		http.Error(w, reason, status)
		return
	}

	sum := hex.EncodeToString(hasher.Sum(nil))
	// MarkQueued writes the state change AND an outbox row (import.requested) in one transaction.
	if err := h.jobs.MarkQueued(ctx, job.ID, objectKey, size, sum); err != nil {
		h.log.ErrorContext(ctx, "mark queued", "job_id", job.ID, "err", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	writeJSON(w, http.StatusAccepted, job.WithState("QUEUED"))
}
```

Things to get right (each is an interview question):
- `http.MaxBytesReader` caps the body. Also set server `ReadTimeout`/`ReadHeaderTimeout` sensibly for large uploads (slowloris protection vs legitimate slow uploads).
- **Idempotency race:** two requests with the same key arrive simultaneously. `UNIQUE(principal_id, idempotency_key)` plus `INSERT ... ON CONFLICT DO NOTHING RETURNING` makes exactly one of them the creator. What should the loser return while the first upload is still in flight?
- **Rate limiting:** per principal token bucket in Valkey (e.g. N uploads/minute, M concurrent uploads).
- **Compressed uploads:** accept `.gz`/`.zst`; decompress in the parser worker, not the gateway, with a decompressed-size cap (zip-bomb defense).

### 3.6 Import job state machine

```
            +-----------+
            | RECEIVING |---- upload error ----> FAILED
            +-----+-----+
                  | stored + outbox row
                  v
            +-----------+
            |  QUEUED   |<----------- retry (attempts < N) ------+
            +-----+-----+                                         |
                  | parser picked up                              |
                  v                                               |
            +-----------+                                         |
            |  PARSING  |---- parser error ----> FAILED_RETRYABLE-+
            +-----+-----+                              |
                  | first batch applied                | attempts >= N
                  v                                    v
            +-------------+                       FAILED (DLQ)
            | RECONCILING |
            +------+------+
                   | all batches 0..last applied
                   v
            +-------------+
            | FINALIZING  |  (close old findings, counts, outbox events)
            +------+------+
                   v
            +-------------+
            |  COMPLETED  |
            +-------------+
```

Every transition is a compare-and-set:

```sql
UPDATE ingest.import_job
   SET state = 'PARSING', attempts = attempts + 1, updated_at = now()
 WHERE id = $1 AND state IN ('QUEUED', 'FAILED_RETRYABLE')
RETURNING attempts;
-- 0 rows updated => someone else owns this transition; do nothing.
```

**Think first:** a parser crashes after emitting batches 0 to 40. On retry it re-emits 0 to 40 (no-ops in the reconciler) and continues. What happens if a *code fix* between attempts changes how findings are split into batches, so batch 12 now contains different findings? How would you make batches content-addressed or attempt-scoped to stay correct?

### 3.7 Deduplication and reimport

#### 3.7.1 How DefectDojo does it (reference)

Per DefectDojo's documentation, there are four deduplication algorithms selectable per parser:

| Algorithm | Matching rule |
|---|---|
| `unique_id_from_tool` | Use the scanner-provided unique identifier; endpoints are ignored |
| `hash_code` | SHA-based hash over a per-scanner configured field list (plus fields that are always included); endpoints can also be required to match |
| `unique_id_from_tool_or_hash_code` | Prefer the tool's unique ID; fall back to the hash path if there's no match |
| `legacy` | Historical multi-condition algorithm, open-source only |

Algorithm and hash fields are configured per parser. Reimport uses its own matching settings, separate from same-tool and cross-tool deduplication that run after findings exist. Changes to dedup configuration are not applied retroactively; there is a management command to recompute hashes.

Reimport outcomes per incoming item: **create**, **leave untouched**, **reactivate** (a previously closed finding reappears), or **close** (an existing finding is absent from the new report, when close-old-findings is enabled). A `do_not_reactivate` option makes the platform, not the scanner, the source of truth for closed findings. Each reimport records created / closed / untouched / reactivated counts in the import history.

Kata implements the first three algorithms. Skip `legacy`.

#### 3.7.2 Hash computation

```python
import hashlib
import re

_WS = re.compile(r"\s+")

def _norm(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ",".join(sorted(_norm(v) for v in value))
    text = str(value).strip().lower()
    return _WS.sub(" ", text)

def compute_hash_code(finding: dict, fields: list[str], always: list[str]) -> str:
    parts = [f"{f}={_norm(finding.get(f))}" for f in [*fields, *always]]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
```

Notes:
- Field names are included in the hashed string (`field=value`), so swapping values between fields cannot collide.
- Lists are sorted, so `vuln_ids` order from the scanner does not matter.
- **Choosing hash fields is the real design work.** Including `line` makes findings "move" (close + create) when code shifts. Including `description` breaks dedup when the scanner updates advisory text. Write down, per scanner, *why* each field is in or out.
- Use Hypothesis (property-based testing) to prove: normalization is idempotent, field order in the dict doesn't matter, and whitespace/case variations hash identically.

#### 3.7.3 Scopes

| Dedup type | Scope | When it runs |
|---|---|---|
| Reimport matching | Within one Test | During reimport, per incoming finding |
| Same-tool dedup | Same Product (or same Engagement if `deduplication_on_engagement`), same scanner | After findings are created |
| Cross-tool dedup | Same Product, any scanner, **hash path only** | After findings are created; needs hash fields that exist across tools (e.g. CVE + component + version) |

When a match is found, the newer finding gets `duplicate_of = <oldest original>`. Duplicates are excluded from "open findings" metrics.

**Ordering and races:** two imports in the same Product can each create an "original" for the same hash concurrently. Options:

| Option | Pros | Cons |
|---|---|---|
| Key Kafka messages by `product_id` (chosen to start) | All batches for a product are processed in order by one consumer; no race | One huge product can't be parallelized; hot partition |
| `pg_advisory_xact_lock(hashtext(product_id || hash_code))` | Fine-grained, parallel | Many locks per batch; lock ordering to avoid deadlocks |
| Allow the race, run a periodic dedup sweep | Max throughput | Temporarily wrong duplicate counts |

Start with product keying. Measure. If one giant product is the bottleneck, that's a great Phase 9 problem.

#### 3.7.4 Reimport algorithm (set-based, scales to millions)

Holding all of a Test's existing findings in a Python dict does not scale (5M entries × Python object overhead is gigabytes). Push the diff into PostgreSQL:

```
Per batch (RECONCILING):
  1. Compute match_key for each incoming finding (uid or hash, per scanner_config).
  2. COPY the batch into a temp staging table: (match_key, finding fields).
  3. INSERT the keys into ingest.reimport_seen (ON CONFLICT DO NOTHING).
  4. Set-based apply:
       a. UNTOUCHED: existing active findings whose key matches
            -> UPDATE last_seen_at
       b. REACTIVATE: existing mitigated findings whose key matches
            -> if do_not_reactivate: leave closed, add audit note
            -> else: status = 'active', mitigated_at = NULL, audit + outbox event
       c. HUMAN-TRIAGED: existing false_positive / out_of_scope / risk_accepted with matching key
            -> leave status alone (human decision wins); update last_seen_at
       d. CREATE: incoming keys with no existing finding in this test
            -> INSERT new findings; run same-tool/cross-tool dedup on them
  5. INSERT (job_id, seq) into ingest.applied_batch in the same transaction.

At FINALIZING (only after all batches 0..last are applied):
  6. Take pg_advisory_xact_lock(test_id).
  7. If close_old_findings:
       candidates = active findings in this test whose key is NOT in reimport_seen for this job
       -> run the mass-closure guard (below)
       -> UPDATE status = 'mitigated', mitigated_at = now(), audit + outbox
  8. Write test_import with counts; DELETE FROM reimport_seen WHERE job_id = ...
  9. Job -> COMPLETED.
```

Core SQL for step 7:

```sql
UPDATE core.finding f
   SET status = 'mitigated', mitigated_at = now(), updated_at = now()
 WHERE f.test_id = $1
   AND f.status = 'active'
   AND NOT EXISTS (
         SELECT 1 FROM ingest.reimport_seen s
          WHERE s.job_id = $2
            AND s.match_key = COALESCE(NULLIF(f.unique_id_from_tool, ''), f.hash_code)
       )
RETURNING f.id;
```

(The `COALESCE` mirrors `unique_id_from_tool_or_hash_code`. For the other algorithms, compute the key expression from `scanner_config`. Better: store the computed `match_key` as a column on `finding` so this join is a plain index lookup.)

**Mass-closure circuit breaker (Kata extension):** if a reimport would close more than X% of a Test's active findings (default 50%) *and* the incoming report is much smaller than the previous one, do not close automatically. Put the job in `NEEDS_CONFIRMATION`, notify the owner, and show a diff preview in the UI. A truncated CI artifact should never mark 40,000 vulnerabilities as fixed.

**Think first:**
1. Batch 7 creates a finding, and batch 9 contains the *same* key again (scanners do emit duplicates within one report). What happens with the logic above? How do you make "create" idempotent within a single job?
2. A human marks a finding `false_positive`. The next reimport no longer contains it. Should it be closed as `mitigated`? What does DefectDojo do? (Look at the reimport discussions in its repository; this exact edge case has been debated and changed over time.)

### 3.8 Finding lifecycle

| From | To | Trigger | Actor |
|---|---|---|---|
| (none) | active | Import / reimport create | import |
| active | mitigated | Reimport close-old-findings; manual close | import / user |
| mitigated | active | Reimport reactivation (unless `do_not_reactivate`); manual reopen | import / user |
| active | false_positive / out_of_scope | Triage | user (Writer+) |
| active | risk_accepted | Added to a risk acceptance | user (Maintainer+) |
| risk_accepted | active | Risk acceptance expired with `reactivate_on_expiry` | scheduler |
| any | (duplicate_of set) | Dedup match | import |
| duplicate | original | Original deleted or reset; promote the oldest duplicate | system |

Implement this as one function `transition(finding, to_status, actor, reason)` that validates the edge, writes the audit row, recomputes SLA if needed and writes the outbox event, all in the caller's transaction. No other code path may update `status` directly. Enforce that with a test that greps for raw status updates, or with a DB trigger.

### 3.9 SLA and risk acceptance

- `sla_due_date = finding.created_date + sla_days[severity]` using the product's SLA configuration. Recompute on severity change and when a risk acceptance expires with `restart_sla_on_expiry`.
- **Scheduler jobs** (daily, plus on demand):
  - SLA breach scan: `WHERE status='active' AND sla_due_date < current_date` (uses `finding_sla_due`), emits `finding.sla_breached` once per finding per breach (store `sla_breach_notified_at`).
  - Risk acceptance expiry: find expired, transition findings, mark `expired_at`.
- **Exactly one scheduler instance runs each job** even with multiple replicas: use a `scheduled_job_run` table and `SELECT ... FOR UPDATE SKIP LOCKED`, or `pg_try_advisory_lock(job_id)`.

### 3.10 REST API contract (core-api, `/api/v1`)

| Method | Path | Purpose | Min role |
|---|---|---|---|
| GET/POST | `/product-types` | List / create | Reader / global Maintainer |
| GET/POST | `/products` | List / create | Reader / Maintainer |
| GET/PATCH/DELETE | `/products/{id}` | Read / update / delete | Reader / Maintainer / Owner |
| GET/POST | `/products/{id}/engagements` | List / create | Reader / Writer |
| GET/POST | `/engagements/{id}/tests` | List / create | Reader / Writer |
| GET | `/tests/{id}/imports` | Import history with counts | Reader |
| GET | `/findings` | Filtered, keyset-paginated list | Reader |
| GET/PATCH | `/findings/{id}` | Read / edit fields | Reader / Writer |
| POST | `/findings/{id}/transitions` | Status change with reason | Writer |
| POST | `/findings/bulk-transitions` | Bulk triage (async for large sets) | Writer |
| GET/POST | `/findings/{id}/notes` | Notes | Reader / Writer |
| GET/POST | `/risk-acceptances` | Risk acceptances | Reader / Maintainer |
| GET/POST | `/api-tokens` | Scoped CI tokens | self |
| GET | `/import-jobs/{id}` | Job status | Reader |
| GET (SSE) | `/import-jobs/{id}/events` | Live progress stream | Reader |
| GET | `/metrics/products/{id}/summary` | Dashboard aggregates | Reader |

Ingest API (`ingest-gateway`, `/ingest/v1`):

| Method | Path | Purpose |
|---|---|---|
| POST | `/uploads` | Streaming upload; `Idempotency-Key` required; query: `scanner`, `mode`, `engagement_id` or `test_id`, options |
| POST | `/uploads/multipart` | Start resumable upload (Phase 4b) |
| PUT | `/uploads/multipart/{id}/parts/{n}` | Upload a part |
| POST | `/uploads/multipart/{id}/complete` | Complete and queue |

**Pagination:** keyset, not offset. `GET /findings?product_id=7&status=active&severity=critical&limit=100&cursor=<opaque>`; the cursor encodes `(severity, id)` of the last row. Offset pagination at 10M rows forces the DB to scan and discard rows; keyset stays fast at any depth. Tradeoff: no "jump to page 9,431". Nobody needs that.

**Errors:** RFC 9457 `application/problem+json`:

```json
{
  "type": "https://kata.dev/problems/invalid-transition",
  "title": "Invalid status transition",
  "status": 409,
  "detail": "Cannot transition finding 812 from 'mitigated' to 'risk_accepted'.",
  "instance": "/api/v1/findings/812/transitions"
}
```

**API tokens:** random 32-byte tokens, shown once, stored as SHA-256 hashes, scoped to products and actions (e.g. "import into product 7 only"), with expiry. CI tokens never get triage rights.

### 3.11 Events and the transactional outbox

| Event | Key | Emitted when |
|---|---|---|
| `import.completed` | product_id | Job finalized (with counts) |
| `import.failed` | product_id | Job terminally failed |
| `finding.created` | product_id | New original finding (aggregated per import, see notifier) |
| `finding.status_changed` | finding_id | Any lifecycle transition |
| `finding.sla_breached` | product_id | Scheduler detects breach |
| `risk_acceptance.expired` | product_id | Scheduler expires acceptance |

**Outbox relay options:**

| Option | Pros | Cons |
|---|---|---|
| Polling relay: `SELECT ... WHERE published_at IS NULL ORDER BY id LIMIT 500 FOR UPDATE SKIP LOCKED` (chosen) | Simple, no extra infra, you learn the mechanics | Polling latency; table churn (vacuum) |
| CDC with Debezium (Apache-2.0) reading the WAL | Low latency, no polling | Kafka Connect cluster, more ops |

Publish, then set `published_at`. If the relay crashes between the two, the event is published again: consumers must be idempotent (dedupe on outbox `id`).

### 3.12 Notifier (Go)

- Channels: SMTP email (Mailpit for local dev), generic webhooks (HMAC-signed), Slack-compatible incoming webhooks, Mattermost (open source), Microsoft Teams webhooks.
- **Aggregation is mandatory:** an import that creates 30,000 findings must produce *one* "import completed: 30,000 new, 112 critical" message, not 30,000 messages. Per-user digests (hourly/daily) for noisy events.
- Subscriptions: `(user_id, product_id | all, event_type, channel)`.
- Delivery: retries with exponential backoff + jitter, max attempts, DLQ table, per-channel circuit breaker so a dead webhook doesn't consume all workers.

### 3.13 Issue tracker sync (integration-sync)

- Targets: GitHub Issues, GitLab Issues, Gitea (all free; GitLab and Gitea are self-hostable). Jira as an optional adapter only.
- Mapping table: `finding_issue_link(finding_id, provider, external_id, last_synced_at, last_external_state)`.
- Outbound: on `finding.created` (by severity threshold) create issue; on status change update/close.
- Inbound: provider webhook → verify signature → map issue closed → transition finding (actor = integration) → avoid ping-pong loops by checking `last_external_state` and actor.
- Rate limits: respect provider limits with a token bucket per installation.

### 3.14 Scan-runner agent (Go)

```yaml
# kata-agent.yaml
server: https://kata.example.dev
token_env: KATA_TOKEN            # scoped API token, never in the file
product: payments-api
engagement: ci-main
scans:
  - scanner: trivy
    args: ["image", "--format", "json", "registry.local/payments:latest"]
    mode: reimport
    test_title: "trivy image payments"
  - scanner: kubescape
    args: ["scan", "framework", "nsa", "--format", "json"]
    mode: reimport
    test_title: "kubescape nsa"
```

| Model | How | Pros | Cons |
|---|---|---|---|
| **Push** (chosen) | Agent runs scanners locally, pushes reports | Kata never holds client credentials; works behind firewalls | Client must run the agent |
| Pull | Kata runs scanners against client infra with stored credentials | Zero client setup | Kata becomes a high-value credential vault; much larger attack surface |

The agent: runs scanners as subprocesses (or containers), enforces timeouts, streams output to a temp file, uploads with idempotency key = hash(config + scan output digest), retries with backoff, exits non-zero on policy failure (e.g. new critical findings) so CI can gate.

### 3.15 Frontend (React)

**Routes and modules (mirroring DefectDojo's navigation):**

| Route | Module | Key behavior |
|---|---|---|
| `/` | Dashboard | Open findings by severity, SLA breaches, recent imports, trends |
| `/products` | Product list | Server-side filter and pagination |
| `/products/:id` | Product detail | Tabs: Overview, Engagements, Findings, Components, Endpoints, Metrics, Members, Settings |
| `/engagements/:id` | Engagement | Tests, import button |
| `/tests/:id` | Test | Findings + import history (created / untouched / reactivated / closed per import) |
| `/findings` | Global findings | Saved filters, bulk triage, virtualized table |
| `/findings/:id` | Finding detail | Fields, status transitions, notes, files, duplicates, history, raw record view |
| `/import` | Import wizard | Upload with progress, live job status (SSE) |
| `/risk-acceptances` | Risk acceptances | Expiry dates, linked findings |
| `/settings/*` | Admin | Users, roles, SLA configs, scanner configs, notifications, API tokens |

**Technical decisions:**

| Concern | Choice | Tradeoff |
|---|---|---|
| Server state | TanStack Query | Caching and invalidation for free; don't mirror server data into a global store |
| Tables | TanStack Table + TanStack Virtual, server-side sort/filter | Never load 100k rows into the browser |
| Live job status | Server-Sent Events | One-way, works over plain HTTP, auto-reconnect. WebSockets are bidirectional but more infra; polling is simplest but wasteful. |
| Charts | Apache ECharts | Handles large series well |
| Auth | OIDC code flow with PKCE against Keycloak | Tokens in memory; refresh via Keycloak |
| Types | Generate TypeScript types from the OpenAPI schema | Contract drift becomes a compile error |

### 3.16 Reporting

Async: `POST /reports` → job → `report-worker` renders HTML template → WeasyPrint → PDF in object storage → presigned download link. CSV exports stream rows with a server-side cursor; never build the whole CSV in memory.

### 3.17 Optional AI module (Phase 10)

Kept last and optional on purpose: it must not be the reason the core is unfinished.

- **Finding summaries and remediation hints** per product or per import ("what changed and what matters").
- **Semantic duplicate suggestions** across tools: embed `title + description + component` into pgvector; *suggest* likely duplicates for human confirmation, never auto-merge.
- **Provider abstraction:** Ollama (self-hosted) by default; OpenRouter or Groq free tiers optional behind the same interface, with rate limits and fallbacks (you have built this kind of gateway before in Forge; reuse the design).
- **Guardrails:** redact secrets and tokens before sending text to any model; record model, prompt version and output for audit; treat model output as untrusted.

---

## Part IV: Scanner and Integration Catalogue

Every tool below is free and open source (or free to use for this purpose). Licenses were correct to the best of available knowledge at the time of writing; **verify each license and the project's maintenance status before writing its parser**, and record the check in the parser's README.

Column guide: **Parser lang** is where the parser lives (Python in `parser-workers` unless a Go port is justified by benchmarks). **Phase** is when to add it.

### 4.1 Generic formats (highest leverage, do these early)

One generic parser unlocks many tools at once. This is the single best return on effort in the catalogue.

| Format | What it covers | Phase | Notes |
|---|---|---|---|
| **SARIF 2.1.0** | Dozens of SAST, IaC and secret scanners (Semgrep, gosec, Checkov, KICS, Gitleaks, Hadolint, kube-linter, OSV-Scanner, Grype...) | 5 | Map `runs[].results[]` + `rules[]`; location from `physicalLocation`. Dedup via `fingerprints`/`partialFingerprints` when present. |
| **CycloneDX** (SBOM + VEX) | Components, and vulnerabilities when present | 5 | Populates `component`; VEX can mark findings `not_affected` |
| **SPDX** (SBOM) | Components | 6 | Components only |
| **Kata Generic JSON** | Anything else: custom tools, scripts | 2 | Your own documented schema, like DefectDojo's Generic Findings Import |
| **OCSF** (finding classes) | Tools emitting OCSF (e.g. Prowler) | 5 | Also a design reference for your canonical model |

### 4.2 Container and dependency vulnerabilities (SCA)

| Tool | Finds | License | Output | Phase | Notes |
|---|---|---|---|---|---|
| **Trivy** | Image/filesystem/repo vulnerabilities, misconfig, secrets, licenses | Apache-2.0 | JSON, SARIF, CycloneDX | **2 (first)** | Native JSON gives the richest data; tfsec's functionality now lives in Trivy |
| Grype | Image and filesystem vulnerabilities | Apache-2.0 | JSON, SARIF, CycloneDX | 5 | Great cross-tool dedup test against Trivy (same CVEs, different IDs/severities) |
| OSV-Scanner | Dependency vulnerabilities from lockfiles via OSV.dev | Apache-2.0 | JSON, SARIF | 5 | |
| OWASP Dependency-Check | Java/.NET/JS dependency CVEs | Apache-2.0 | XML, JSON | 6 | Good streaming **XML** parser exercise |
| pip-audit | Python dependencies | Apache-2.0 | JSON | 6 | |
| npm audit | Node dependencies | (bundled with npm) | JSON | 6 | Format changed across npm versions: version-detect in `sniff` |
| govulncheck | Go vulnerabilities, reachability-aware | BSD-3 | JSON (stream of messages) | 6 | Interesting because it reports *reachability* |
| Dockle | Container image config best practices | Apache-2.0 | JSON | 6 | |
| OWASP Dependency-Track | SBOM-based component risk platform | Apache-2.0 | REST API | 7 | Pull connector: Kata reads findings via its API (DefectDojo has a similar integration) |

### 4.3 SBOM and supply chain

| Tool | Purpose | License | Output | Phase |
|---|---|---|---|---|
| Syft | Generate SBOMs from images/filesystems | Apache-2.0 | CycloneDX, SPDX, JSON | 5 |
| OpenSSF Scorecard | Repository supply-chain posture checks | Apache-2.0 | JSON | 6 |

### 4.4 Infrastructure as Code and configuration

| Tool | Finds | License | Output | Phase |
|---|---|---|---|---|
| Checkov | Terraform, CloudFormation, K8s manifests, Helm, Dockerfile misconfig | Apache-2.0 | JSON, SARIF | 5 |
| KICS | Similar scope to Checkov | Apache-2.0 | JSON, SARIF | 6 |
| Trivy (config mode) | IaC misconfig | Apache-2.0 | JSON, SARIF | 5 (reuse Trivy parser) |
| Hadolint | Dockerfile lint | GPL-3.0 | JSON, SARIF | 6 (via SARIF) |

### 4.5 Kubernetes posture

| Tool | Finds | License | Output | Phase | Notes |
|---|---|---|---|---|---|
| **Kubescape** | NSA/CISA, MITRE, CIS framework controls on clusters and manifests | Apache-2.0 | JSON, SARIF | **2 (first)** | Resource-centric findings: forces the `K8sLocation` design early |
| kube-bench | CIS Kubernetes Benchmark checks on nodes | Apache-2.0 | JSON | 5 | Node-level; on managed clusters only worker checks apply |
| Polaris | Workload best practices | Apache-2.0 | JSON | 6 | |
| kube-linter | Manifest/Helm static checks | Apache-2.0 | JSON, SARIF | 6 (via SARIF) | |
| Popeye | Live cluster sanitizer | Apache-2.0 | JSON | 6 | |
| ~~kube-hunter~~ | Attacker-view probing | Apache-2.0 | JSON | skip | Aqua says it is no longer actively developed; use only for legacy samples |
| ~~kubeaudit~~ | Workload audit | MIT | JSON | skip | Archived by Shopify in October 2024 |

### 4.6 Cloud security posture (CSPM)

| Tool | Clouds | License | Output | Phase | Notes |
|---|---|---|---|---|---|
| **Prowler** | AWS, Azure, GCP, Kubernetes, more | Apache-2.0 | JSON-OCSF, CSV, HTML | 5 | Best-maintained open CSPM option; OCSF output aligns with your canonical model |
| ScoutSuite | AWS, Azure, GCP | GPL-2.0 | Results embedded in a JS file next to the HTML report | 6 | Unusual format (strip the JS assignment, then parse JSON). Check recent release activity before investing time. |
| CloudSploit | AWS, Azure, GCP, OCI | GPL-3.0 | JSON, CSV | 7 | Check maintenance status first |

You can run these against a free-tier cloud account or against intentionally vulnerable labs. Never scan accounts you don't own.

### 4.7 Static application security testing (SAST)

| Tool | Languages | License | Output | Phase | Notes |
|---|---|---|---|---|---|
| Semgrep Community Edition | Many | LGPL-2.1 (engine) | JSON, SARIF | 5 (via SARIF) | Rule packs from the Semgrep registry have their own license terms; check before redistributing |
| Bandit | Python | Apache-2.0 | JSON | 5 | |
| gosec | Go | Apache-2.0 | JSON, SARIF | 5 (via SARIF) | |
| SonarQube Community Build | Many | LGPL-3.0 | REST API | 7 | Pull connector via API, like DefectDojo's SonarQube integration |
| MobSF | Android/iOS apps | GPL-3.0 | JSON | 8 | Mobile static analysis |

### 4.8 Secrets detection

| Tool | License | Output | Phase | Notes |
|---|---|---|---|---|
| Gitleaks | MIT | JSON, SARIF | 5 | |
| TruffleHog (open source) | AGPL-3.0 | JSON lines | 6 | Has secret *verification*; never store raw secret values in Kata, only redacted fingerprints |
| detect-secrets | Apache-2.0 | JSON baseline | 6 | |

**Rule for this whole category:** findings must never persist the secret itself. Store a redacted preview and a hash. Add a test that fails if a parser output contains a known test secret in cleartext.

### 4.9 Dynamic application security testing (DAST)

| Tool | License | Output | Phase | Notes |
|---|---|---|---|---|
| ZAP | Apache-2.0 | JSON, XML | 6 | Endpoint-centric: exercises `Endpoint` + `finding_endpoint_status` |
| Nuclei | MIT | JSON lines | 5 | Template-based; huge volume of findings; good streaming test |
| Nikto | GPL-2.0 | XML, JSON | 7 | |
| Wapiti | GPL-2.0 | JSON | 7 | |

Run DAST only against targets you own or intentionally vulnerable apps (OWASP Juice Shop, DVWA) in your lab.

### 4.10 Network and infrastructure

| Tool | License | Output | Phase | Notes |
|---|---|---|---|---|
| Nmap | Nmap Public Source License (free to use; custom, not OSI) | XML | 7 | Open ports and service versions → endpoints |
| testssl.sh | GPL-2.0 | JSON, CSV | 7 | TLS configuration findings |
| SSLyze | AGPL-3.0 | JSON | 7 | |
| Greenbone / OpenVAS Community Edition | GPL / AGPL | XML | 8 | Heavy to run; parser practice with large XML |

### 4.11 Malware and data (PII) scanning (Kata extension)

DefectDojo doesn't specialize here. Treat these as "adapters": Kata runs or receives results from these tools and converts them into findings.

| Tool | Purpose | License | Output | Phase | Notes |
|---|---|---|---|---|---|
| ClamAV | Malware signatures in files/images | GPL-2.0 | Text log | 10 | Parse `clamscan` output lines; the agent can scan image layers |
| YARA | Pattern-based malware rules | BSD-3 | Text / `yara-python` | 10 | Rule sets have their own licenses |
| Microsoft Presidio | PII detection in text | MIT | Library (Python) | 10 | Run in the agent against files/buckets; emit Kata Generic JSON |

### 4.12 Runtime security events (Kata extension, last)

| Tool | License | Output | Phase | Notes |
|---|---|---|---|---|
| Falco | Apache-2.0 | JSON events | 10 | Events are a *stream*, not a report: aggregate by (rule, workload) into findings with counts and first/last seen |
| Tetragon | Apache-2.0 | JSON events | 10 | Same aggregation model |

Keep this phase last and optional. It is closest to your day job; the earlier phases are what make this project show *different* skills.

### 4.13 Excluded (paid / proprietary)

Checkmarx, Snyk, Veracode, Burp Suite Professional, Nessus, Qualys, Prisma Cloud, Wiz and similar are excluded. DefectDojo supports many of their formats. If you ever want to practice those parsers, DefectDojo's repository ships sample scan files in its unit tests under its BSD-3-Clause license; check the license and attribute properly before using them as fixtures. CodeQL is free for open-source repositories but has license restrictions otherwise; treat it as optional via SARIF.

### 4.14 Outbound and inbound integrations

| Integration | Direction | Free option | Phase |
|---|---|---|---|
| Issue trackers | Out + webhook in | GitHub Issues, GitLab Issues (self-host or free tier), Gitea (self-host) | 7 |
| Jira | Out + in | Optional adapter only (SaaS) | optional |
| Email | Out | Any SMTP; Mailpit for dev | 7 |
| Chat | Out | Mattermost (self-host), Slack/Teams incoming webhooks | 7 |
| Generic webhooks | Out | HMAC-signed JSON | 7 |
| CI templates | In | GitHub Actions, GitLab CI examples calling the ingest API | 7 |
| Kubernetes CronJob | In | `scan-runner` agent Helm chart | 7 |
| API pull connectors | In | Dependency-Track, SonarQube Community, Prowler output buckets | 7 |
| SSO | Auth | Keycloak (OIDC); GitHub/Google as identity providers via Keycloak | 1 |

---

## Part V: Macroscope Plan

### 5.1 Phase map

Durations assume about 12 to 15 focused hours per week alongside a full-time job. Adjust honestly after Phase 1 based on your real pace.

| Phase | Name | Goal | Duration | Resume signal unlocked |
|---|---|---|---|---|
| 0 | Foundations | Repo, tooling, local stack, CI, observability skeleton | 1 week | — |
| 1 | Core domain and API | Hierarchy, users, RBAC, findings list, React shell | 3 weeks | "Designed multi-tenant RBAC enforced in the data layer" |
| 2 | Import v1 (in-process) | Trivy + Kubescape import end to end, small files | 2 weeks | — (internal milestone) |
| 3 | Dedup and reimport | 3 dedup algorithms, set-based reimport, import history, mass-closure guard | 3 weeks | "Set-based reimport diffing over millions of findings" |
| 4 | Ingestion plane | Go gateway, object storage, Kafka, streaming parsers, reconciler, idempotency, DLQ, live progress | 4 weeks | **Headline:** "Streaming ingestion of 10 GB reports at X findings/sec with bounded memory" |
| 5 | Scanner breadth I | SARIF, CycloneDX, Grype, OSV, Checkov, Bandit, Gitleaks, Nuclei, kube-bench, Prowler | 2 weeks | "Pluggable parser SDK, N scanners" |
| 6 | Triage workflows | Notes, files, tags, transitions, risk acceptance, SLA, endpoints, components, audit log, finding groups | 3 weeks | — (parity) |
| 7 | Events and integrations | Outbox relay, notifier, issue sync, webhooks, scan-runner agent, CI templates | 3 weeks | "Transactional outbox + event-driven integrations" |
| 8 | Metrics and reporting | Dashboards, MTTR, SLA compliance, trends, PDF/CSV export | 2 weeks | — |
| 9 | Hardening and operations | Helm on k3s, SLOs and alerts, chaos tests, parser sandboxing, load tests, backups | 2 weeks | "Chaos-tested pipeline; SLO-based alerting" |
| 10 | Extensions (optional) | AI module, runtime events, malware/PII adapters, scanner breadth II | open-ended | AI-engineering signal |

**Total for Phases 0 to 9:** roughly 25 weeks part-time.

### 5.2 The MVP cut (what makes it resume-worthy)

**Phases 0 to 4 are the core** (about 13 weeks). At the end of Phase 4 you have:
- A real domain model with RBAC,
- Import and reimport with DefectDojo-style dedup,
- A streaming ingestion pipeline with a measured benchmark,
- A live demo with seeded data.

That alone is a strong project. Everything after Phase 4 is breadth and parity. If life gets busy, stop after Phase 4, polish the README and benchmarks, and ship it.

### 5.3 Critical path and dependencies

```
P0 ──> P1 ──> P2 ──> P3 ──> P4 ──┬──> P5 ──┐
                                 ├──> P6 ──┼──> P8 ──> P9
                                 └──> P7 ──┘
                                              P10 (any time after P9, optional)
```

- P3 depends on P2 because dedup needs real parsed findings.
- P4 depends on P3 because the reconciler *is* the dedup/reimport logic, moved out of process. Build it in-process first, so you know what correct behavior looks like before distributing it.
- P5, P6 and P7 can be interleaved.

### 5.4 Phase exit criteria (summary)

| Phase | Exit criteria |
|---|---|
| 0 | `docker compose up` brings up Postgres, Valkey, Keycloak, Grafana stack; CI runs lint + tests on every push |
| 1 | A Reader cannot see another product's findings (tested); keyset pagination p95 < 300 ms at 1M seeded findings |
| 2 | Trivy and Kubescape sample reports import correctly (golden tests); import history recorded |
| 3 | Parity harness: same fixture sequence imported into DefectDojo and Kata yields matching created/untouched/reactivated/closed counts (or documented, intentional differences) |
| 4 | 10 GB synthetic report imports successfully; parser RSS stays under 512 MB; killing any worker mid-import produces zero duplicate findings and zero wrongful closures; benchmark published |
| 5 | Each new parser has golden tests; SARIF parser validated against at least 4 tools' output |
| 6 | Every status change produces an audit row and passes through `transition()` (enforced by test) |
| 7 | One import of 30k findings produces one notification; issue sync round-trips without loops |
| 8 | Dashboards render under 1 s on 10M findings (materialized views or projection) |
| 9 | Helm install on k3s from scratch works; chaos suite passes; alerts fire on induced failures |

---

## Part VI: Microscope Plan

Format for each phase: **Tasks** (checkboxes), **Deliverables**, **ADRs to write**, **Think first** (answer these in writing *before* building), and **Done when**.

### Phase 0: Foundations (1 week)

**Tasks**
- [x] Create monorepo with the layout in Part X; add `README.md`, `LICENSE` (choose one: MIT or Apache-2.0), `CONTRIBUTING.md`.
- [x] Python tooling: `uv` (or Poetry), `ruff`, `mypy --strict`, `pytest`; shared `pyproject` settings.
- [x] Go tooling: Go modules, `golangci-lint`, `go test ./...`.
- [x] Frontend: Vite + React + TypeScript strict mode, ESLint, Prettier, Vitest.
- [x] `docker-compose.yml` with profiles: `core` (Postgres, Valkey, Keycloak), `ingest` (Kafka KRaft, SeaweedFS), `observability` (OTel Collector, Prometheus, Grafana, Loki, Tempo).
- [x] Makefile / Taskfile targets: `up`, `down`, `test`, `lint`, `migrate`, `seed`.
- [x] GitHub Actions: lint + unit tests for Python, Go, web; Buf lint; build images. (Note: no service Dockerfiles exist in Phase 0, so the "build images" job is a `docker compose config` validation for now; image builds are added as services gain Dockerfiles.)
- [x] `docs/adr/0000-template.md`; write ADR-001 (architecture style) from Part II. (ADR-0001 status: **accepted**.)
- [ ] Install DefectDojo locally (separate compose project). Import one Trivy report. Explore every screen. Take notes on what you see. (Owner: you — per kickoff.md.)

**Deliverables:** running local stack, green CI, ADR-001.

**Think first**
- Monorepo or polyrepo for Python + Go + React? What does each cost you in CI time and shared contracts?
- What is the minimum observability you need on day one so that Phase 4 debugging is possible?

**Done when:** a fresh clone runs `make up && make test` successfully.

### Phase 1: Core domain and API (3 weeks)

**Week 1: Schema and domain**
- [x] Alembic migrations for `core` schema: product_type, product, engagement, test, scanner_config, component, finding (status enum), sla_configuration, test_import, audit_log. (Applied + reversible against local PG; audit_log partitioned with DEFAULT + current-month partitions. Monthly partition-creation *job* deferred to the Phase 6 scheduler; DEFAULT partition keeps inserts safe meanwhile.)
- [~] SQLAlchemy 2.x models + repository layer (`kata-domain` package). (Models done for the Week-1 table set; **repository layer still to build**.)
- [x] `transition()` service for finding status (Part III 3.8), with unit tests for every allowed and forbidden edge. (78 tests; DB-free via a structural session protocol.)
- [ ] Seed script: generate 1M synthetic findings across 50 products (use `COPY`, not ORM inserts).

**Week 2: Auth and RBAC**
- [x] Keycloak realm export committed to the repo (users, clients) for reproducible setup. (`deploy/compose/config/keycloak/kata-realm.json`, imported via `--import-realm`; realm `kata`, clients `kata-web`/`kata-core-api`, PKCE + audience mapper.)
- [x] OIDC JWT validation middleware in FastAPI with cached JWKS. (`auth.verify_jwt` via PyJWT `PyJWKClient`.)
- [x] Roles and memberships (global, product type, product); `user_product_access` maintenance. (migration 0002; `recompute_user_product_access` set-based.)
- [x] One `authorized_findings_query(user)` builder used by every finding query. (`repositories.list_findings` + `effective_role`/`get_finding_authorized`.)
- [~] Scoped API tokens: create (show once), hash at rest, scopes, expiry, revoke. (Create/hash/scopes/expiry done; **list/revoke endpoints still to add**.)
- [~] Tests: cross-tenant access attempts return 404 (not 403). (Data-layer isolation tested; 404-vs-403 enforced in routes + ADR-0008; **per-endpoint 404 API tests for a non-admin principal still to add**.)

**Week 3: API and UI shell**
- [x] CRUD endpoints for the hierarchy; findings list with filters + keyset pagination; OpenAPI published.
- [x] RFC 9457 error handler.
- [~] React shell: login, layout, product list, findings table. (TanStack Query + router + typed client; products→findings works against the live API. **Dev-header login for now (OIDC PKCE wiring pending); table not yet virtualized**.)
- [x] Generate TS types from OpenAPI in CI. (`make openapi` → `npm run gen:api`; CI fails on spec/type drift.)
- [x] Benchmark: findings list p95 at 1M rows with `EXPLAIN ANALYZE` captured in `docs/benchmarks/phase1.md`. (p95 = 1.6 ms.)

**ADRs:** status enum vs booleans (0002); 404 vs 403 (0008); keyset pagination (0006); FastAPI vs Django (0007). Also: engagement immutability (0003), audit strategy (0004), RBAC model (0005).

**Think first**
- You denormalized `product_id` onto `finding`. What happens when someone moves an engagement to another product? Is that operation allowed?
- Should audit logging be done in application code or via DB triggers? What does each miss?

**Done when:** RBAC test suite passes; p95 target met; you can click through products to findings in the UI.

### Phase 2: Import v1, in-process (2 weeks)

**Tasks**
- [ ] Parser SDK (`kata_parsers`): base classes, registry, limits, `ParserError`.
- [ ] Generate real sample reports: Trivy against 3 public images (small, medium, large); Kubescape against a local kind cluster with intentionally bad manifests. Commit small samples as fixtures; keep large ones out of git.
- [ ] Trivy parser (vulnerabilities + misconfigurations) with streaming.
- [ ] Kubescape parser (controls → findings per failed resource).
- [ ] Kata Generic JSON parser + JSON Schema for it.
- [ ] Golden tests: `fixture.json → expected.jsonl`, with a `--update-golden` flag.
- [ ] `POST /api/v1/import` (synchronous, small files only, size-capped) → creates Test, findings, `test_import` row.
- [ ] Import page in UI; Test page shows findings and import history.

**ADRs:** canonical finding model (include the `Location` generalization); how severities from different tools are normalized.

**Think first**
- Kubescape reports one control failing on 200 resources. Is that 1 finding or 200? What does DefectDojo do? What does a security engineer *want* to triage?
- Trivy reports the same CVE in the same package in 3 different image layers. Same question.

**Done when:** both scanners import end to end via UI and API; golden tests green.

### Phase 3: Deduplication and reimport (3 weeks)

**Week 1: Hashing and dedup**
- [ ] `scanner_config` seeded with algorithm + hash fields per scanner, with a written rationale per field.
- [ ] `compute_hash_code` + Hypothesis property tests.
- [ ] Store `match_key` on `finding`.
- [ ] Same-tool dedup (product scope, engagement scope flag) and cross-tool dedup (hash path).
- [ ] Duplicate promotion when an original is deleted.
- [ ] Management command: recompute hashes for a scanner after config change (dry-run mode showing what would change).

**Week 2: Reimport**
- [ ] `POST /api/v1/reimport` with `close_old_findings`, `do_not_reactivate`.
- [ ] Set-based reimport diff via staging (Part III 3.7.4), still in-process.
- [ ] Human-triaged statuses are never overridden by the scanner.
- [ ] Mass-closure circuit breaker + `NEEDS_CONFIRMATION` state + UI confirm/reject.
- [ ] `test_import` counts; Test page timeline of imports.

**Week 3: Parity harness**
- [ ] Script that runs a fixture *sequence* (import v1, reimport v2 with 3 fixed + 2 new, reimport v3 with 1 regression...) against both DefectDojo's API and Kata's API, then compares created/untouched/reactivated/closed counts.
- [ ] Document every intentional difference in `docs/parity.md`.

**ADRs:** hash field choices per scanner; dedup ordering strategy (product keying); mass-closure guard thresholds.

**Think first**
- A finding is closed by reimport, then a human reopens it manually, then the next reimport doesn't contain it. What should happen?
- Is cross-tool dedup even safe between Trivy and Grype if they disagree on severity? Which severity does the original keep?

**Done when:** parity harness passes or every difference is documented and justified.

### Phase 4: Ingestion plane (4 weeks)

**Week 1: Gateway and object storage (4a)**
- [ ] Go `ingest-gateway`: auth (API tokens + JWT), streaming upload, SHA-256 tee, size cap, idempotency, rate limit.
- [ ] `ingest.import_job` + gateway outbox; job state machine with CAS transitions.
- [ ] SeaweedFS S3 adapter + local filesystem adapter behind one interface.
- [ ] Synthetic report generator: produces valid Trivy-format JSON of any size (1 MB to 10 GB) with a controllable duplicate ratio. This is your benchmark tool; make it deterministic (seeded).

**Week 2: Kafka and parser workers**
- [ ] Topics: `import.requested`, `findings.normalized`, `import.status`, DLQ topics; partitions sized for local benchmarks; retention settings documented.
- [ ] Protobuf contracts + Buf; generated Go and Python code.
- [ ] Outbox relay (Go) for `import.requested`.
- [ ] Parser worker: consume, stream from object storage, decompress with caps, parse, batch (500, zstd), produce with `job_id`/`seq`, trace headers.
- [ ] Graceful shutdown; retries; DLQ after N attempts.

**Week 3: Reconciler**
- [ ] Move Phase 3 logic into the reconciler process (same `kata-domain` package).
- [ ] Batch apply with `COPY` into staging + set-based SQL; `applied_batch` idempotency in the same transaction.
- [ ] Finalization trigger when `applied_batches == total_batches`; advisory lock per test.
- [ ] Feature flag: route imports to in-process path or ingestion plane; run both on the same fixtures and diff results.

**Week 4: Progress, chaos, benchmark (4b)**
- [ ] SSE endpoint for job progress; UI progress bar with live counts.
- [ ] Resumable multipart uploads.
- [ ] Chaos tests: kill parser mid-file, kill reconciler mid-batch, restart Kafka, restart Postgres. Assert: no duplicate findings, no wrongful closures, job eventually completes or fails cleanly.
- [ ] Benchmark matrix: file size (100 MB, 1 GB, 10 GB) × duplicate ratio (0%, 50%, 95%) × workers (1, 2, 4). Record throughput, e2e time, peak RSS per service, Postgres write rate, consumer lag. Publish in `docs/benchmarks/phase4.md` with charts.
- [ ] Optional: port the hottest step (often hashing + batching) to Go; benchmark Python vs Go side by side.

**ADRs:** Kafka vs NATS; partition key choice; batch size; upload protocol; why unlogged staging tables.

**Think first**
- Where is the bottleneck going to be: parsing CPU, Kafka, or Postgres writes? Write your prediction down *before* the first benchmark, then compare. (This habit is very valuable in interviews.)
- If you double parser workers but the reconciler is keyed by `product_id` and you import into one product, what speedup do you expect? Why?

**Done when:** Phase 4 exit criteria in 5.4 pass and the benchmark is published.

### Phase 5: Scanner breadth I (2 weeks)

**Tasks**
- [ ] SARIF parser (generic): rules, results, locations, fingerprints → `unique_id_from_tool` when stable.
- [ ] Validate SARIF parser against real output of Semgrep, gosec, Checkov, Gitleaks (and KICS, kube-linter if time).
- [ ] CycloneDX parser: components + vulnerabilities; VEX `not_affected` handling.
- [ ] Native parsers: Grype, OSV-Scanner, Bandit, Nuclei (JSON lines), kube-bench, Prowler (OCSF JSON).
- [ ] Cross-tool dedup test: Trivy vs Grype on the same image; document the match rate and why misses happen.
- [ ] Parser "contract test" template so each new parser takes under a day.

**Think first:** SARIF `partialFingerprints` differ between tools and versions. When is it safe to use them as `unique_id_from_tool`?

**Done when:** 10+ scanners supported with golden tests; cross-tool dedup measured.

### Phase 6: Triage workflows (3 weeks)

**Tasks**
- [ ] Finding detail: notes, file attachments (object storage, size and type limits, malware-scan hook placeholder), tags.
- [ ] Bulk transitions (async job for > 1,000 findings).
- [ ] Risk acceptance: create, attach findings, expiry, reactivation, SLA restart option.
- [ ] SLA configuration per product; due date calculation; scheduler with SKIP LOCKED single-run guarantee.
- [ ] Endpoints + endpoint status (mitigate per endpoint); components page with versions and linked findings.
- [ ] Finding groups (by component or by vulnerability).
- [ ] Audit log UI per finding and per product; monthly partition maintenance job.
- [ ] Test that fails if any code updates `finding.status` outside `transition()`.

**Think first:** a risk acceptance covers 500 findings and expires at midnight. The scheduler runs on 3 replicas. How do you guarantee each finding is reactivated exactly once and exactly one notification is sent?

**Done when:** a security engineer could triage a real product end to end in the UI.

### Phase 7: Events and integrations (3 weeks)

**Tasks**
- [ ] Core outbox writes for all domain events (same transaction as the change).
- [ ] Outbox relay for `domain.events`; consumer-side dedup on event id.
- [ ] Notifier: subscriptions, channels (SMTP/Mailpit, webhook with HMAC, Mattermost/Slack-compatible), per-import aggregation, digests, retries, DLQ, per-channel circuit breaker.
- [ ] Integration-sync: GitHub Issues (create/update/close, inbound webhooks with signature verification, loop prevention); GitLab as second provider behind the same interface.
- [ ] `scan-runner` agent (Go): YAML config, subprocess execution with timeouts, upload with idempotency, CI exit codes, Dockerfile, Helm chart for CronJob mode.
- [ ] CI templates: GitHub Actions workflow and GitLab CI job that run the agent.
- [ ] Pull connectors: Dependency-Track API (and SonarQube Community if time).

**Think first:** an issue is closed in GitHub, which transitions the finding to mitigated, which emits `finding.status_changed`, which integration-sync consumes... How do you stop the loop without losing legitimate updates?

**Done when:** Phase 7 exit criteria in 5.4 pass.

### Phase 8: Metrics and reporting (2 weeks)

**Tasks**
- [ ] Metric definitions written first: open by severity over time, new vs closed per week, MTTR by severity, SLA compliance %, top components, aging buckets.
- [ ] Implementation via PostgreSQL materialized views refreshed on import completion (debounced) and on a schedule.
- [ ] Measure dashboard queries at 10M findings; only if they miss the 1 s target, add a ClickHouse projection fed from `domain.events` (write an ADR either way).
- [ ] Dashboard and product metrics pages (ECharts).
- [ ] Report worker: PDF (WeasyPrint) and streaming CSV export via async job + download link.

**Think first:** "open findings by day for the last 90 days" requires knowing state *at each day*. Your `finding` table only has current state. What do you need to store to answer it correctly?

**Done when:** dashboards meet the latency target; reports export correctly.

### Phase 9: Hardening and operations (2 weeks)

**Tasks**
- [ ] Helm chart for all services; values for "laptop" and "single VM"; install on k3s from scratch.
- [ ] Probes, resource requests/limits, PodDisruptionBudgets, HPA on parser workers (CPU or consumer lag via KEDA, Apache-2.0).
- [ ] Parser sandboxing: non-root, read-only root FS, seccomp `RuntimeDefault`, drop all capabilities, NetworkPolicy allowing only Kafka + object storage.
- [ ] Security review of Kata itself: run Trivy, Semgrep, Gitleaks and ZAP against Kata, and import the results into Kata. (Good README screenshot.)
- [ ] SLOs + Prometheus alert rules: e2e import latency, consumer lag, DLQ growth, error rates.
- [ ] Backups: `pg_dump`/WAL archiving to object storage; restore drill documented and timed.
- [ ] Load test: k6 or Locust for the API under concurrent imports.
- [ ] Final docs: architecture diagram, runbooks for top 5 failure modes, benchmark summary.

**Done when:** Phase 9 exit criteria pass and a stranger could install and run Kata from the README.

### Phase 10: Extensions (optional)

Pick at most one at a time:
- [ ] AI module (Part III 3.17) with Ollama default, evaluation set of 50 hand-labeled findings to measure summary quality and duplicate-suggestion precision.
- [ ] Falco/Tetragon event aggregation into findings.
- [ ] ClamAV/YARA/Presidio adapters in the agent.
- [ ] Scanner breadth II from the catalogue.

---

## Part VII: Testing Strategy

| Layer | Tooling | What it covers |
|---|---|---|
| Unit | pytest, Go `testing`, Vitest | Pure logic: hashing, transitions, mappers, SLA math |
| Property-based | Hypothesis | Hash normalization invariants, transition graph invariants |
| Golden files | pytest with fixtures | Every parser: raw report → expected canonical findings |
| Contract | Buf breaking checks; OpenAPI diff | Producer/consumer compatibility |
| Integration | testcontainers (Postgres, Kafka, SeaweedFS) | Repository SQL, reconciler batches, outbox relay |
| Parity | Custom harness vs a local DefectDojo | Import/reimport outcomes match the reference system |
| End to end | Playwright | Login → import → triage → reimport → dashboard |
| Load | k6 / Locust; synthetic report generator | API latency and pipeline throughput |
| Chaos | Scripted container kills/restarts during imports | Idempotency and no-wrongful-closure guarantees |
| Security | Kata scanning itself; fuzzing parsers with malformed inputs (Atheris for Python, Go native fuzzing) | Parser robustness against hostile reports |

The **chaos test** and the **parity harness** are the two tests that most clearly demonstrate senior-level thinking. Prioritize them.

---

## Part VIII: Benchmarks and Resume Narrative

### 8.1 What to measure and publish

| Benchmark | Record |
|---|---|
| Import throughput | findings/sec by file size, duplicate ratio, worker count |
| End-to-end time | p50/p95 per size bucket |
| Memory | Peak RSS per parser worker vs input size (should be flat) |
| Reimport | Time to reimport 5M findings with 98% untouched |
| API | Findings list p95 at 1M and 10M rows |
| Recovery | Time to complete an import after killing each component mid-run |
| Before/after | In-process import (Phase 3) vs ingestion plane (Phase 4) on the same files |

### 8.2 Resume bullet templates

Fill in only with numbers you actually measured:

```
• Rebuilt the core architecture of OWASP DefectDojo from scratch (Python, Go, React):
  multi-tenant findings model with RBAC, import/reimport, and three deduplication
  strategies, validated against DefectDojo with a parity test harness.

• Designed an event-driven ingestion pipeline (Go gateway, Kafka, streaming parsers,
  idempotent reconciler) that imports [X] GB reports at [Y] findings/sec with
  under [Z] MB memory per worker; zero duplicates or lost updates under chaos tests.

• Implemented set-based reimport diffing in PostgreSQL that reconciles [N]M findings
  in [T] s, plus a mass-closure circuit breaker that blocks truncated reports from
  closing real vulnerabilities.
```

### 8.3 Interview story arcs this project gives you

| Story | Source phase |
|---|---|
| "Why I didn't start with microservices, and when I extracted one" | 2.2, Phase 4 |
| "How I made an at-least-once pipeline behave effectively-once" | 3.5 to 3.7, Phase 4 |
| "The bottleneck I predicted vs the one I found" | Phase 4 benchmark |
| "A correctness bug that would close real vulnerabilities, and the guard I built" | 3.7.4 |
| "Where I diverged from DefectDojo and why" | 3.1, 3.3, parity doc |

---

## Part IX: Risks and Anti-Patterns

| Risk / anti-pattern | Symptom | Prevention |
|---|---|---|
| Scope explosion | 40 half-written parsers, no working reimport | Phases 0 to 4 first; parsers only after the pipeline is proven |
| Distributed monolith | Services that must deploy together; synchronous calls chains between them | Only the ingestion plane is async and separate; everything else stays in `core-api` |
| Premature Go rewrite | Rewriting Python before measuring | Port a component only with a benchmark showing it is the bottleneck |
| N+1 queries in reconcile | Throughput collapses as tables grow | Set-based SQL, `COPY`, `EXPLAIN ANALYZE` in benchmark docs |
| Trusting scanner output | Parser crash or exploit via crafted report | Streaming, limits, defusedxml, fuzzing, sandboxed workers |
| Storing secrets from secret scanners | Kata becomes a secret store | Redaction at parse time + test |
| Notification storms | 30k messages per import | Aggregation per import and digests |
| Silent dedup misconfiguration | Duplicates explode or real findings merge | `dedup_match_ratio` metric, dry-run recompute command |
| Copying DefectDojo code | Learn little; licensing obligations | Design first, compare after; attribute anything reused |
| Unfinished project | Strong idea, nothing to show | MVP cut after Phase 4 with a polished README and benchmark |

---

## Part X: Repository Layout

```
kata/
├── README.md
├── docs/
│   ├── adr/                      # 0000-template.md, 0001-architecture-style.md, ...
│   ├── benchmarks/               # phase1.md, phase4.md (+ charts)
│   ├── parity.md                 # differences vs DefectDojo
│   └── runbooks/
├── proto/                        # kata/ingest/v1/*.proto, buf.yaml
├── services/
│   ├── core-api/                 # Python, FastAPI
│   ├── parser-workers/           # Python
│   ├── reconciler/               # Python (later: Go port of hot path)
│   ├── scheduler/                # Python
│   ├── report-worker/            # Python
│   ├── integration-sync/         # Python
│   ├── ingest-gateway/           # Go
│   ├── outbox-relay/             # Go
│   └── notifier/                 # Go
├── packages/
│   ├── kata-domain/              # Python: models, repositories, transition(), dedup, reimport
│   ├── kata-parsers/             # Python: SDK + parsers + golden fixtures
│   └── kata-go-common/           # Go: auth, telemetry, kafka helpers
├── agent/                        # Go: scan-runner
├── web/                          # React + TypeScript
├── tools/
│   ├── synthetic-report-gen/     # deterministic large report generator
│   ├── parity-harness/           # DefectDojo vs Kata comparison
│   └── chaos/                    # failure injection scripts
├── deploy/
│   ├── compose/                  # docker-compose.yml + profiles
│   └── helm/kata/
└── .github/workflows/
```

---

## Appendix A: ADR Template

```markdown
# ADR-NNNN: <decision title>

- Status: proposed | accepted | superseded by ADR-XXXX
- Date: YYYY-MM-DD

## Context
What problem, what constraints, what forces are in tension.

## Options considered
| Option | Pros | Cons |
|---|---|---|

## Decision
What we chose.

## Consequences
What gets easier, what gets harder, what we must now monitor.

## How DefectDojo does it
(Filled in AFTER the decision.) Same or different? Why?

## Revisit when
The measurable condition that would make us reconsider.
```

## Appendix B: Glossary

| Term | Meaning |
|---|---|
| Product Type | Top-level grouping of products (team, business unit) |
| Product | An application or system being secured |
| Engagement | A time-boxed or CI/CD testing effort on a product |
| Test | One scanner's results within an engagement; reimport targets a Test |
| Finding | One security issue instance |
| Original / duplicate | Dedup links a newer finding to the oldest matching original |
| Reimport | Diffing a new report against an existing Test |
| Close old findings | Marking findings absent from a new report as mitigated |
| Hash code | SHA-256 over configured normalized fields |
| Unique ID from tool | Scanner-provided stable identifier |
| Outbox | Table of events written in the same transaction as state changes |
| DLQ | Dead-letter queue for messages that repeatedly fail |
| Keyset pagination | Paging by "rows after this key" instead of offset |

## Appendix C: References

- DefectDojo architecture (open source): https://docs.defectdojo.com/get_started/open_source/architecture/
- DefectDojo running in production: https://docs.defectdojo.com/get_started/open_source/running-in-production/
- DefectDojo deduplication algorithms: https://docs.defectdojo.com/en/working_with_findings/finding_deduplication/deduplication_algorithms
- DefectDojo deduplication tuning (open source): https://docs.defectdojo.com/triage_findings/finding_deduplication/os__deduplication_tuning/
- DefectDojo reimport: https://docs.defectdojo.com/import_data/import_intro/reimport
- DefectDojo source: https://github.com/DefectDojo/django-DefectDojo
- SARIF 2.1.0 specification (OASIS)
- CycloneDX and SPDX specifications
- OCSF schema (Vulnerability Finding, Compliance Finding classes)
- RFC 9457 (Problem Details for HTTP APIs)
- *Designing Data-Intensive Applications* (Kleppmann): chapters on replication, partitioning, stream processing; read alongside Phase 4
