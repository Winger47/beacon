"""In-process import service (Phase 2): parse a report stream into findings for a Test.

This is the synchronous, small-file path. Deduplication/hashing is Phase 3; the extracted
streaming ingestion plane (gateway → Kafka → reconciler) with job state machine and
idempotency is Phase 4. Here we simply: resolve the parser, create a Test, stream-insert
findings, and record the test_import row — all in the caller's transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy.orm import Session

from kata_domain import repositories as repo
from kata_domain.enums import Severity as DomainSeverity
from kata_domain.models import Engagement, Finding
from kata_parsers import Finding as ParsedFinding
from kata_parsers import get_parser


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


def _to_domain_finding(
    session: Session, parsed: ParsedFinding, *, test_id: int, engagement_id: int, product_id: int
) -> Finding:
    component_id: int | None = None
    if parsed.component_name:
        component = repo.get_or_create_component(
            session, name=parsed.component_name, version=parsed.component_version
        )
        component_id = component.id

    location = list(parsed.locations) if parsed.locations else None
    return Finding(
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
        location=location,
    )


def import_scan(
    session: Session,
    *,
    engagement: Engagement,
    scanner_key: str,
    stream: BinaryIO,
    title: str | None = None,
    max_bytes: int | None = None,
) -> ImportResult:
    """Parse ``stream`` with the scanner's parser and create a Test + its findings.

    ``max_bytes`` caps the synchronous path (Phase 2); exceeding it raises
    :class:`ImportTooLarge`. ``get_parser`` raises ``ParserError`` for an unknown scanner and
    the parser raises it for malformed input — both propagate to the caller.
    """
    parser = get_parser(scanner_key)
    read_stream: BinaryIO = stream if max_bytes is None else _CappedReader(stream, max_bytes)  # type: ignore[assignment]
    test = repo.create_test(
        session, engagement_id=engagement.id, scanner_key=scanner_key, title=title
    )

    created = 0
    for parsed in parser.parse(read_stream):
        repo.add_finding(
            session,
            _to_domain_finding(
                session,
                parsed,
                test_id=test.id,
                engagement_id=engagement.id,
                product_id=engagement.product_id,
            ),
        )
        created += 1

    job_id = str(uuid.uuid4())
    repo.create_test_import(
        session, test_id=test.id, import_job_id=job_id, kind="import", created_count=created
    )
    session.flush()
    return ImportResult(test_id=test.id, import_job_id=job_id, created_count=created)
