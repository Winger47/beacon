# ADR-0007: FastAPI + SQLAlchemy over Django + DRF

- Status: accepted
- Date: 2026-11-03

## Context

DefectDojo (the reference) is Django + DRF. Kata's primary goal is *learning* backend
engineering — especially the SQL behind ingestion, dedup and reimport. The ORM choice
therefore matters for learning, not just delivery speed.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| Django + DRF (DefectDojo) | Fast CRUD, free admin, batteries included, matches reference | The ORM hides the SQL we are trying to learn; migrations are implicit; and the builder already knows Django (less learning) |
| FastAPI + SQLAlchemy 2.x + Alembic + Pydantic v2 (**chosen**) | Explicit SQL (Core/ORM), explicit Alembic migrations, async-ready, Pydantic contracts and auto OpenAPI; forces us to own the data layer | More wiring (no free admin); must build auth/token pieces ourselves |

## Decision

FastAPI + SQLAlchemy 2.x + Alembic + Pydantic v2. We write the set-based SQL for the hot
paths ourselves (dedup, reimport, keyset) — which is the point. Auto-generated OpenAPI drives
the TypeScript client types. Keycloak handles identity; we build API tokens ourselves.

## Consequences

- Easier: the SQL is explicit and benchmarkable (`EXPLAIN ANALYZE` in the benchmark docs);
  contracts are typed end to end (Pydantic → OpenAPI → TS).
- Harder: no free Django admin; we hand-build auth, token issuance and some CRUD plumbing.
- Must monitor: keep business logic in `kata-domain`, not in route handlers (CLAUDE.md #5).

## How DefectDojo does it

Django + DRF, uWSGI behind NGINX. We diverge deliberately for learning value and explicit SQL.

## Revisit when

Delivery speed outweighs learning (it does not for this project), or async DB access becomes
a measured need.
