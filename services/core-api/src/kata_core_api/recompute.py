"""Recompute finding hashes for a scanner after a dedup-config change (project.md 3.7, Week 1).

Dedup config changes are NOT retroactive (ADR-0011): existing findings keep the hash they were
stored with. This command rehashes a scanner's findings under the *current* ``scanner_config``
and reports what would change. It is dry-run by default; ``--apply`` writes the new
hash/match_key and re-runs dedup.

This is an offline maintenance command, so the per-row recompute loop is acceptable (unlike the
request hot path, CLAUDE.md #9). It never changes finding status.

Usage:
    python -m kata_core_api.recompute --scanner trivy            # dry-run
    python -m kata_core_api.recompute --scanner trivy --apply
"""

from __future__ import annotations

import argparse

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from kata_domain import dedup, hashing
from kata_domain.models import Component, Finding, ScannerConfig, Test

from .db import make_engine, make_session_factory, session_scope

_CROSS_TOOL_FIELDS = ("vuln_ids", "component_name", "component_version")


def _fields_from_row(
    finding: Finding, component: Component | None, scanner_key: str
) -> dict[str, object]:
    return {
        "scanner_key": scanner_key,
        "title": finding.title,
        "vuln_ids": list(finding.vuln_ids),
        "cwe": finding.cwe,
        "component_name": component.name if component else "",
        "component_version": component.version if component else "",
        "file_path": finding.file_path,
        "severity": finding.severity.value,
        "description": finding.description or "",
        "unique_id_from_tool": finding.unique_id_from_tool or "",
    }


def recompute_scanner(session: Session, *, scanner_key: str, apply: bool) -> tuple[int, int]:
    """Rehash a scanner's findings. Returns (examined, changed). Writes only when ``apply``."""
    config = session.get(ScannerConfig, scanner_key)
    if config is None:
        raise SystemExit(f"no scanner_config for {scanner_key!r}")

    rows = session.execute(
        select(Finding, Component)
        .join(Test, Test.id == Finding.test_id)
        .outerjoin(Component, Component.id == Finding.component_id)
        .where(Test.scanner_key == scanner_key)
    ).all()

    examined = 0
    changed = 0
    product_ids: set[int] = set()
    for finding, component in rows:
        examined += 1
        fields = _fields_from_row(finding, component, scanner_key)
        new_hash = hashing.compute_hash_code(fields, config.hash_fields)
        new_cross = (
            hashing.compute_hash_code(fields, _CROSS_TOOL_FIELDS, always=())
            if finding.vuln_ids and component is not None
            else None
        )
        new_key = hashing.match_key(
            algorithm=config.dedup_algorithm,
            unique_id_from_tool=finding.unique_id_from_tool,
            hash_code=new_hash,
        )
        if (new_hash, new_cross, new_key) != (
            finding.hash_code,
            finding.cross_tool_hash,
            finding.match_key,
        ):
            changed += 1
            product_ids.add(finding.product_id)
            if apply:
                finding.hash_code = new_hash
                finding.cross_tool_hash = new_cross
                finding.match_key = new_key

    if apply and changed:
        session.flush()
        # Reset duplicate links for affected products, then re-dedup under the new hashes.
        for pid in product_ids:
            session.execute(
                text(
                    "UPDATE core.finding SET duplicate_of = NULL "
                    "WHERE product_id = :pid AND duplicate_of IS NOT NULL"
                ),
                {"pid": pid},
            )
            dedup.run_same_tool_dedup(session, product_id=pid, scanner_key=scanner_key)
            dedup.run_cross_tool_dedup(session, product_id=pid)
    return examined, changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute finding hashes for a scanner.")
    parser.add_argument("--scanner", required=True)
    parser.add_argument(
        "--apply", action="store_true", help="write changes (default: dry-run)"
    )
    args = parser.parse_args()

    engine: Engine = make_engine()
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        examined, changed = recompute_scanner(
            session, scanner_key=args.scanner, apply=args.apply
        )
    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"[{mode}] scanner={args.scanner}: examined={examined} changed={changed}")


if __name__ == "__main__":
    main()
