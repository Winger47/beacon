"""Run the parity sequence against every configured backend and diff the counts.

Usage (Kata must be up: ``make up && make migrate``, with ``KATA_DEV_AUTH=true``)::

    uv run python -m scripts.parity.run --base-url http://localhost:8001

Exit code is non-zero if any backend's counts diverge from the oracle, so this doubles as a
CI gate. Point it at a live DefectDojo with ``DEFECTDOJO_URL`` / ``DEFECTDOJO_TOKEN`` /
``DEFECTDOJO_ENGAGEMENT_ID`` to add the second backend. See docs/parity.md.
"""

from __future__ import annotations

import argparse
import sys

from .backends import Backend, DefectDojoBackend, KataBackend
from .scenario import Counts, Step, default_sequence, expected_counts

_HEADS = ("created", "untouched", "reactivated", "closed")


def _run_backend(backend: Backend, steps: list[Step]) -> list[Counts]:
    backend.bootstrap()
    return [backend.run_step(step) for step in steps]


def _fmt(c: Counts) -> str:
    return f"{c.created:>3} {c.untouched:>3} {c.reactivated:>3} {c.closed:>3}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3 reimport parity harness.")
    parser.add_argument("--base-url", default="http://localhost:8001", help="Kata core-api URL")
    parser.add_argument("--dev-user", default="parity@kata.dev", help="X-Kata-Dev-User subject")
    parser.add_argument("--scanner", default="trivy", help="Kata scanner_key")
    args = parser.parse_args(argv)

    steps = default_sequence()
    oracle = expected_counts(steps)

    backends: list[Backend] = [
        KataBackend(args.base_url, dev_user=args.dev_user, scanner=args.scanner)
    ]
    dd = DefectDojoBackend.from_env()
    if dd is not None:
        backends.append(dd)
    else:
        print("note: DefectDojo backend skipped (DEFECTDOJO_URL/TOKEN unset)\n")

    results: dict[str, list[Counts]] = {}
    for backend in backends:
        try:
            results[backend.name] = _run_backend(backend, steps)
        except Exception as exc:  # report any backend failure, keep going
            print(f"backend {backend.name!r} failed: {exc}", file=sys.stderr)
            results[backend.name] = []

    print(f"{'step':<34} {'backend':<11} {'  '.join(h[:4] for h in _HEADS)}   verdict")
    print("-" * 78)
    mismatches = 0
    for i, step in enumerate(steps):
        want = oracle[i]
        print(f"{step.label:<34} {'oracle':<11} {_fmt(want)}")
        for name, rows in results.items():
            if i >= len(rows):
                print(f"{'':<34} {name:<11} {'(no result)':<16} FAIL")
                mismatches += 1
                continue
            got = rows[i]
            ok = got.as_tuple() == want.as_tuple()
            if not ok:
                mismatches += 1
            print(f"{'':<34} {name:<11} {_fmt(got)}   {'ok' if ok else 'MISMATCH'}")
        print()

    if mismatches:
        print(f"PARITY FAILED: {mismatches} mismatch(es) against the oracle.")
        return 1
    print("PARITY OK: all backends match the oracle for every step.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
