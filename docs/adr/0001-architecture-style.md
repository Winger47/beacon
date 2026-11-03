# ADR-0001: Architecture style

- Status: proposed
- Date: 2026-11-03

## Context

Kata reimplements DefectDojo's core. DefectDojo is a Django monolith served by uWSGI behind
NGINX, with Celery workers for background work (dedup, JIRA sync), Celery Beat for scheduled
jobs, Valkey as broker, and PostgreSQL as the only database. That is a sound design for its
workload.

Kata's primary learning goal is high-volume ingestion: streaming multi-GB untrusted reports,
normalization, deduplication, idempotency, and async pipelines. The forces in tension:

- **Ingestion** is bursty, CPU- and I/O-heavy, handles untrusted multi-GB input, and must not
  take down interactive triage. Its scaling and failure profile is distinct.
- **Triage / CRUD** is low-volume and naturally transactional (a finding update + audit row +
  outbox row belong in one transaction).
- As a solo developer, distributed transactions and a 12-service sprawl would cost far more
  than they return.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| Monolith + task queue (DefectDojo) | Simple deploys, one transaction boundary, fast to build | Large imports compete with web traffic for the same workers and DB connections; one bad parser can OOM a shared worker |
| Modular monolith | Clear module boundaries, one deployable | Does not isolate ingestion's resource profile |
| Full microservices (one service per entity) | Independent deploys | Distributed transactions for naturally transactional triage; a "distributed monolith" for a solo dev |
| Modular monolith core + extracted ingestion plane (**chosen**) | Ingestion scales and fails independently; core stays transactional and simple | Two deployment units; async pipeline needs idempotency and observability work |

## Decision

Kata is a **modular monolith core (`core-api`) plus an extracted, event-driven ingestion plane**
(ingest-gateway → Kafka → parser-workers → reconciler), plus a few small edge services
(notifier, scheduler, outbox-relay, integration-sync, scan-runner agent).

Split along **scaling and failure profiles, not along nouns.** Splitting "products" and
"engagements" into separate services would buy nothing but distributed transactions.

**Sequencing (anti-sprawl):** Phases 1–3 run everything inside `core-api` with a simple
in-process import, so correct behavior is understood first. The ingestion plane is *extracted*
in Phase 4, once the domain is understood. Do not build 12 services in Phase 1.

## Consequences

- Easier: ingestion can scale on Kafka partitions / CPU and fail without touching triage;
  the transactional core keeps dedup + upsert + audit + outbox in one local transaction.
- Harder: two deployment units to reason about; the async pipeline requires idempotent
  consumers (`applied_batch`, idempotency keys, upserts by natural key), backpressure, and
  distributed tracing to debug.
- Must monitor: end-to-end import latency, consumer-group lag, DLQ growth, and the
  reimport outcome mix (mass-closure anomalies).

## How DefectDojo does it

Monolith + Celery task queue; dedup and integrations run as Celery tasks in workers that share
resources with the web tier. Kata keeps the monolith idea for the transactional core but
redesigns only the part with a genuinely different scaling profile (ingestion). This section is
revisited after Phase 4 with measured before/after numbers (in-process vs ingestion plane).

## Revisit when

- A measured bottleneck shows the transactional core itself needs to split (unlikely at this
  scale), or
- The ingestion plane's two-unit operational cost outweighs its isolation benefit in practice.
