# Contributing to Kata

Kata is a solo learning project. These notes keep the working style consistent; the binding
rules live in [`CLAUDE.md`](./CLAUDE.md) and the design in [`defectdojo.md`](./defectdojo.md).

## Working agreement (summary)

- **Work one phase at a time**, in the order of `defectdojo.md` Part V. Do not start later-phase work.
- **Design before code.** Every non-trivial decision gets an ADR in `docs/adr/` (template:
  `docs/adr/0000-template.md`). Propose the ADR, get approval, then implement.
- **Clone the design, not the code.** DefectDojo is a behavioral reference only; never copy its source.
- **Measure everything.** A phase is done only when its exit criteria (5.4) pass, with numbers.

## Code standards

| Language | Format / lint | Types | Test |
|---|---|---|---|
| Python 3.12+ | `ruff` | `mypy --strict` | `pytest` (parsers: golden-file tests) |
| Go | `golangci-lint` | — | `go test ./...` |
| TypeScript | ESLint + Prettier | `tsc` strict | Vitest / Playwright |

Other hard rules (see `CLAUDE.md`): no business logic in route handlers (domain logic lives in
`packages/kata-domain`); every finding status change goes through `transition()`; parsers stream
untrusted input with size/depth caps; never log report contents or secrets; set-based SQL only.

## Commits & branches

- Conventional-style messages (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
- Never commit to the default branch directly for feature work; branch first.
- Every change ships with tests.

## Local setup

```bash
uv sync                 # Python deps (workspace)
make up                 # local stack
make test && make lint  # before every commit
```
