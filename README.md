# Kata

A from-scratch reimplementation of OWASP DefectDojo's core architecture, with a redesigned
streaming ingestion pipeline. Built for learning high-volume backend engineering: ingestion,
normalization, deduplication, idempotency, and async pipelines.

> The full design and phased plan is in [`defectdojo.md`](./defectdojo.md) (the project's
> design document / "source of truth"; `CLAUDE.md` refers to it as `project.md`).
> Read the relevant Part and Phase before starting any task.

## Status

**Phase 0 — Foundations.** Repo, tooling, local stack, CI, and observability skeleton.
No domain code yet. See the phase map in `defectdojo.md` Part V.

## Stack

| Layer | Tech |
|---|---|
| Core API, parsers, reconciler, scheduler, workers | Python 3.12+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2 |
| Ingestion plane, relays, agent | Go |
| Web | React + TypeScript (strict), Vite, TanStack |
| Data / infra | PostgreSQL, Valkey, Apache Kafka (KRaft), SeaweedFS, Keycloak |
| Contracts | Protocol Buffers + Buf |
| Observability | OpenTelemetry, Prometheus, Grafana, Loki, Tempo |

Free and open-source dependencies only.

## Repository layout

```
docs/      ADRs, benchmarks, parity notes, runbooks
proto/     Protobuf contracts (buf)
services/  Deployable services (core-api, ingest-gateway, reconciler, ...)
packages/  Shared libraries (kata-domain, kata-parsers, kata-go-common)
agent/     scan-runner agent (Go)
web/       React + TypeScript SPA
tools/     synthetic-report-gen, parity-harness, chaos
deploy/    docker-compose (+ profiles) and Helm chart
```

## Quick start

Requires: Docker, `uv`, Node 20+, Go 1.22+ (Go/buf/golangci-lint only needed for Go & proto work).

```bash
make up              # start the 'core' profile (Postgres, Valkey, Keycloak, Caddy)
make up PROFILE=full # everything, incl. ingest + observability
make test            # run unit tests across languages
make lint            # lint across languages
make down            # stop the stack
```

Compose profiles: `core`, `ingest`, `observability`, `full`. See `deploy/compose/`.

## License

[Apache-2.0](./LICENSE).
