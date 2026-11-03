# Kata: working agreement for Claude Code

## What this project is
Kata is a from-scratch reimplementation of OWASP DefectDojo's core architecture, built for
learning backend engineering. The full design and plan is in `project.md`. It is the source
of truth. Read the relevant Part and Phase sections before starting any task.

## Stack
- core-api, parser-workers, reconciler, scheduler, report-worker, integration-sync: Python 3.12+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2
- ingest-gateway, outbox-relay, notifier, scan-runner agent: Go
- web: React + TypeScript (strict) + Vite, TanStack Query/Table/Virtual
- PostgreSQL, Valkey, Apache Kafka (KRaft), SeaweedFS, Keycloak
- Free and open-source dependencies only. Before adding any dependency, state its license.
  Never add MongoDB, MinIO, Redis (use Valkey), Redpanda, or any paid SaaS.

## Hard rules
1. Never copy code from the DefectDojo repository. Use DefectDojo only as a behavioral
   reference (its docs and observed behavior). If asked how DefectDojo does something,
   say so explicitly and summarize; do not paste its code.
2. Work one phase at a time, in the order of project.md Part V. Do not start work belonging
   to a later phase. If a task needs something from a later phase, stop and tell me.
3. Respect the "You build / Claude builds" split below. For "You build" items, do NOT write
   the implementation. Write the interface, the failing tests and a short explanation of the
   problem, then stop and wait for my code. After I write it, review it like a strict tech lead.
4. Every non-trivial design choice gets an ADR in docs/adr/ using the template in project.md
   Appendix A. Propose the ADR first; implement after I approve it.
5. No business logic in route handlers. Domain logic lives in packages/kata-domain.
6. Every finding status change goes through transition() in kata-domain. Never update
   finding.status anywhere else.
7. Parsers stream input. Never json.load()/read() a whole report. Treat every report as
   untrusted input (size caps, depth caps, defusedxml).
8. Never log report contents or secrets.
9. Set-based SQL for anything that touches many findings. No per-row queries in loops.
10. Every change ships with tests. Parsers get golden-file tests.
11. Strict typing: mypy --strict for Python, TypeScript strict mode, golangci-lint for Go.

## You build / Claude builds
I (the human) write these myself. Claude writes interfaces, failing tests and reviews only:
- Hash computation and normalization (project.md 3.7.2)
- Same-tool and cross-tool dedup matching (3.7.3)
- Reimport diff SQL, finalization and close-old-findings (3.7.4)
- Mass-closure circuit breaker (3.7.4)
- Import job state machine transitions and idempotency handling (3.5, 3.6)
- The first Trivy parser (3.4); Claude may write later parsers after reviewing mine
Everything else Claude may implement, after explaining the plan.

## How to work with me
- Before implementing, give a short plan: files to touch, approach, tradeoffs, open questions.
  Wait for my go-ahead on anything that changes the design in project.md.
- Before each phase, ask me the "Think first" questions from that phase in project.md Part VI
  and wait for my written answers. Challenge weak answers before we proceed.
- When I make a design mistake, don't silently fix it. Point it out and ask a question that
  leads me to the problem.
- Keep the phase task checklist in project.md updated (tick boxes as tasks finish).
- At the end of each phase, run the exit criteria from project.md 5.4 and report results
  with numbers. A phase is not done until its exit criteria pass.

## Commands
(fill in as they are created)
- make up / make down / make test / make lint / make migrate / make seed