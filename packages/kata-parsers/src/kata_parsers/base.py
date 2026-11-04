"""Parser SDK base classes (project.md 3.4).

Rules for every parser:
  1. Input is untrusted. Never ``json.load()``/``read()`` the whole file — stream it.
  2. A parser maps raw records to ``Finding``s and nothing else: no DB, no dedup, no network.
  3. A parser is a generator; memory stays flat as input grows.
  4. Every parser ships with golden-file tests.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import BinaryIO, ClassVar

logger = logging.getLogger(__name__)


class Severity(IntEnum):
    INFO = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    CRITICAL = 5

    @classmethod
    def from_text(cls, value: str | None) -> Severity:
        mapping = {
            "critical": cls.CRITICAL,
            "high": cls.HIGH,
            "medium": cls.MEDIUM,
            "moderate": cls.MEDIUM,
            "low": cls.LOW,
            "info": cls.INFO,
            "informational": cls.INFO,
            "unknown": cls.INFO,
            "negligible": cls.INFO,
            "none": cls.INFO,
        }
        if value is None:
            return cls.INFO
        return mapping.get(value.strip().lower(), cls.INFO)

    @property
    def label(self) -> str:
        """Lowercase label matching core.severity (info/low/medium/high/critical)."""
        return self.name.lower()


@dataclass(frozen=True, slots=True)
class Finding:
    """Canonical in-process finding emitted by parsers (Phase 2).

    The Protobuf ``NormalizedFinding`` (3.3) is the wire contract for the Phase 4 ingestion
    plane; this dataclass is its in-process equivalent. ``locations`` is the generalized
    location (file/image/k8s/cloud/endpoint) — see ADR-0009.
    """

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
    locations: tuple[dict[str, object], ...] = ()
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Stable dict for golden-file comparison (severity as its lowercase label)."""
        d = asdict(self)
        d["severity"] = self.severity.label
        d["vuln_ids"] = list(self.vuln_ids)
        d["locations"] = list(self.locations)
        return d


@dataclass(frozen=True, slots=True)
class ParserLimits:
    max_finding_bytes: int = 256 * 1024  # truncate absurd descriptions
    max_findings: int = 50_000_000  # hard stop for runaway input
    max_json_depth: int = 64


class ParserError(Exception):
    """Malformed input. Message must be safe to show users (never raw report content)."""


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
