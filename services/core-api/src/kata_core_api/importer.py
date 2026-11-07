"""In-process import/reimport service (Phase 2 + Phase 3).

Phase 2 gave the synchronous, size-capped parse → insert path. Phase 3 adds the dedup keys
(``hash_code``/``cross_tool_hash``/``match_key`` per ``scanner_config``, ADR-0011), same-tool
and cross-tool deduplication after import, and the set-based reimport diff with the
mass-closure circuit breaker (kata_domain.reimport, ADR-0012/0013).

The extracted streaming ingestion plane (gateway → Kafka → reconciler) with the job state
machine is Phase 4. Here everything happens in the caller's transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy.orm import Session

from kata_domain import dedup, hashing
from kata_domain import repositories as repo
from kata_domain.enums import Severity as DomainSeverity
from kata_domain.models import Engagement, Finding, ScannerConfig, Test
from kata_domain.reimport import BreakerConfig, IncomingFinding, ReimportOutcome, reimport
from kata_parsers import Finding as ParsedFinding
from kata_parsers import get_parser

# Cross-tool dedup key: the scanner-independent subset that exists across SCA tools (ADR-0011).
_CROSS_TOOL_FIELDS = ("vuln_ids", "component_name", "component_version")


class ImportTooLarge(Exception):
    """The uploaded report exceeded the synchronous import size cap (Phase 2)."""


@dataclass(frozen=True, slots=True)
class ImportResult:
    test_id: int
    import_job_id: str
    created_count: int


class _CappedReader:
    """Wrap a binary stream so parsing aborts once ``max_bytes`` have been read.

    The parser streams (never ``read()`` whole), so the cap is enforced incrementally as
    ijson pulls bytes — a 10 GB upload is rejected after ~``max_bytes``, not after buffering
    it. Raises :class:`ImportTooLarge`, which the HTTP layer maps to 413.
    """

    def __init__(self, stream: BinaryIO, max_bytes: int) -> None:
        self._stream = stream
        self._max = max_bytes
        self._seen = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        self._seen += len(chunk)
        if self._seen > self._max:
            raise ImportTooLarge(f"report exceeds the {self._max}-byte import limit")
        return chunk


def _file_path_of(parsed: ParsedFinding) -> str | None:
    for loc in parsed.locations:
        fp = loc.get("file_path")
        if isinstance(fp, str) and fp:
            return fp
    return None


def _hash_fields(parsed: ParsedFinding, scanner_key: str) -> dict[str, object]:
    """Canonical field map a scanner's hash list draws from (names match ADR-0011)."""
    return {
        "scanner_key": scanner_key,
        "title": parsed.title,
        "vuln_ids": list(parsed.vuln_ids),
        "cwe": parsed.cwe,
        "component_name": parsed.component_name,
        "component_version": parsed.component_version,
        "file_path": _file_path_of(parsed),
        "severity": parsed.severity.label,
        "description": parsed.description,
        "unique_id_from_tool": parsed.unique_id_from_tool,
    }


def _compute_keys(
    parsed: ParsedFinding, config: ScannerConfig
) -> tuple[str, str | None, str]:
    """Return (hash_code, cross_tool_hash, match_key) for one parsed finding."""
    fields = _hash_fields(parsed, config.scanner_key)
    hash_code = hashing.compute_hash_code(fields, config.hash_fields)
    cross_tool_hash: str | None = None
    if parsed.vuln_ids and parsed.component_name:
        cross_tool_hash = hashing.compute_hash_code(fields, _CROSS_TOOL_FIELDS, always=())
    key = hashing.match_key(
        algorithm=config.dedup_algorithm,
        unique_id_from_tool=parsed.unique_id_from_tool,
        hash_code=hash_code,
    )
    return hash_code, cross_tool_hash, key


def _to_domain_finding(
    session: Session,
    parsed: ParsedFinding,
    config: ScannerConfig,
    *,
    test_id: int,
    engagement_id: int,
    product_id: int,
) -> tuple[Finding, str]:
    """Build a Finding ORM row (keys computed) and return it with its match_key."""
    component_id: int | None = None
    if parsed.component_name:
        component = repo.get_or_create_component(
            session, name=parsed.component_name, version=parsed.component_version
        )
        component_id = component.id

    hash_code, cross_tool_hash, match_key = _compute_keys(parsed, config)
    location = list(parsed.locations) if parsed.locations else None
    finding = Finding(
        test_id=test_id,
        engagement_id=engagement_id,
        product_id=product_id,
        title=parsed.title,
        severity=DomainSeverity(parsed.severity.label),
        description=parsed.description or None,
        mitigation=parsed.mitigation or None,
        references_text=parsed.references or None,
        cwe=parsed.cwe,
        vuln_ids=list(parsed.vuln_ids),
        cvss_v3_vector=parsed.cvss_v3_vector or None,
        cvss_v3_score=parsed.cvss_v3_score,
        unique_id_from_tool=parsed.unique_id_from_tool or None,
        vuln_id_from_tool=parsed.vuln_id_from_tool or None,
        component_id=component_id,
        file_path=_file_path_of(parsed),
        location=location,
        hash_code=hash_code,
        cross_tool_hash=cross_tool_hash,
        match_key=match_key,
    )
    return finding, match_key


def _resolve_config(session: Session, scanner_key: str) -> ScannerConfig:
    config = repo.get_scanner_config(session, scanner_key)
    if config is None:
        from kata_parsers import ParserError

        raise ParserError(f"no scanner_config for '{scanner_key}'")
    return config


def import_scan(
    session: Session,
    *,
    engagement: Engagement,
    scanner_key: str,
    stream: BinaryIO,
    title: str | None = None,
    max_bytes: int | None = None,
) -> ImportResult:
    """Parse ``stream`` into a new Test's findings, compute dedup keys, run dedup.

    ``max_bytes`` caps the synchronous path (Phase 2); exceeding it raises
    :class:`ImportTooLarge`. Unknown scanner / malformed input raise ``ParserError``.
    """
    parser = get_parser(scanner_key)
    config = _resolve_config(session, scanner_key)
    read_stream: BinaryIO = stream if max_bytes is None else _CappedReader(stream, max_bytes)  # type: ignore[assignment]
    test = repo.create_test(
        session, engagement_id=engagement.id, scanner_key=scanner_key, title=title
    )

    created = 0
    for parsed in parser.parse(read_stream):
        finding, _ = _to_domain_finding(
            session,
            parsed,
            config,
            test_id=test.id,
            engagement_id=engagement.id,
            product_id=engagement.product_id,
        )
        repo.add_finding(session, finding)
        created += 1

    session.flush()
    # Dedup runs after findings exist (3.7.3): point duplicates at their oldest original.
    dedup.run_same_tool_dedup(
        session, product_id=engagement.product_id, scanner_key=scanner_key
    )
    dedup.run_cross_tool_dedup(session, product_id=engagement.product_id)

    job_id = str(uuid.uuid4())
    repo.create_test_import(
        session, test_id=test.id, import_job_id=job_id, kind="import", created_count=created
    )
    session.flush()
    return ImportResult(test_id=test.id, import_job_id=job_id, created_count=created)


def reimport_scan(
    session: Session,
    *,
    test: Test,
    stream: BinaryIO,
    close_old_findings: bool = True,
    do_not_reactivate: bool = False,
    actor_id: str,
    max_bytes: int | None = None,
    breaker: BreakerConfig | None = None,
) -> ReimportOutcome:
    """Parse ``stream`` and diff it against ``test``'s existing findings (3.7.4).

    Uses the Test's own scanner (reimport is same-scanner by definition). Returns the
    :class:`ReimportOutcome`; a tripped mass-closure breaker yields ``needs_confirmation``.
    """
    parser = get_parser(test.scanner_key)
    config = _resolve_config(session, test.scanner_key)
    read_stream: BinaryIO = stream if max_bytes is None else _CappedReader(stream, max_bytes)  # type: ignore[assignment]

    incoming: list[IncomingFinding] = []
    for parsed in parser.parse(read_stream):
        finding, match_key = _to_domain_finding(
            session,
            parsed,
            config,
            test_id=test.id,
            engagement_id=test.engagement_id,
            product_id=test.engagement.product_id,
        )
        incoming.append(IncomingFinding(match_key=match_key, finding=finding))

    job_id = str(uuid.uuid4())
    return reimport(
        session,
        test=test,
        incoming=incoming,
        job_id=job_id,
        actor_id=actor_id,
        close_old_findings=close_old_findings,
        do_not_reactivate=do_not_reactivate,
        breaker=breaker,
    )
