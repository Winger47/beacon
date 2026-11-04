"""Kata Generic JSON parser (project.md 4.1): our own documented format for any tool.

Format (streamed, never loaded whole):

    {
      "schema": "kata-generic-v1",
      "findings": [
        {
          "title": "…",                     # required
          "severity": "high",               # info|low|medium|high|critical (case-insensitive)
          "description": "…", "mitigation": "…", "references": "…",
          "vuln_ids": ["CVE-2026-1"], "cwe": 79,
          "cvss_v3_vector": "…", "cvss_v3_score": 7.5,
          "unique_id_from_tool": "…", "vuln_id_from_tool": "…",
          "component": {"name": "pkg", "version": "1.0"},
          "locations": [{"kind": "file", "path": "a.py", "line": 10}],
          "extra": {"k": "v"}
        }
      ]
    }
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from importlib import resources
from typing import BinaryIO

import ijson

from .base import Finding, ParserError, ScannerParser, Severity
from .registry import register

SCHEMA_RESOURCE = "kata-generic-v1.schema.json"


def generic_schema() -> dict[str, object]:
    """Load the Kata Generic v1 JSON Schema (packaged alongside this module).

    The schema is the published *contract* for the format; parsing itself stays streaming
    (ijson) and never loads the whole report. Callers that want up-front validation of a
    small, trusted document (e.g. a conformance test) can validate against this.
    """
    import json

    text = (resources.files(__package__) / "schemas" / SCHEMA_RESOURCE).read_text("utf-8")
    result: dict[str, object] = json.loads(text)
    return result


def _as_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, Decimal)):
        return int(value)
    try:
        return int(str(value))
    except ValueError:
        return None


def _as_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


@register
class GenericJsonParser(ScannerParser):
    scanner_key = "generic"

    def sniff(self, head: bytes) -> bool:
        return b'"findings"' in head and (b"kata-generic" in head or b'"severity"' in head)

    def parse(self, stream: BinaryIO) -> Iterator[Finding]:
        emitted = 0
        try:
            for raw in ijson.items(stream, "findings.item"):
                if not isinstance(raw, dict):
                    raise ParserError("each finding must be an object")
                title = str(raw.get("title") or "").strip()
                if not title:
                    raise ParserError("finding is missing a title")
                comp = raw.get("component") or {}
                vuln_ids = tuple(str(v) for v in (raw.get("vuln_ids") or []))
                locations = tuple(
                    loc for loc in (raw.get("locations") or []) if isinstance(loc, dict)
                )
                extra_raw = raw.get("extra") or {}
                extra = {str(k): str(v) for k, v in extra_raw.items()}

                yield Finding(
                    title=title[:500],
                    severity=Severity.from_text(raw.get("severity")),
                    description=str(raw.get("description") or "")[: self.limits.max_finding_bytes],
                    mitigation=str(raw.get("mitigation") or ""),
                    references=str(raw.get("references") or ""),
                    vuln_ids=vuln_ids,
                    cwe=_as_int(raw.get("cwe")),
                    cvss_v3_vector=str(raw.get("cvss_v3_vector") or ""),
                    cvss_v3_score=_as_float(raw.get("cvss_v3_score")),
                    unique_id_from_tool=str(raw.get("unique_id_from_tool") or ""),
                    vuln_id_from_tool=str(raw.get("vuln_id_from_tool") or ""),
                    component_name=str(comp.get("name") or "") if isinstance(comp, dict) else "",
                    component_version=str(comp.get("version") or "")
                    if isinstance(comp, dict)
                    else "",
                    locations=locations,
                    extra=extra,
                )
                emitted += 1
                if emitted >= self.limits.max_findings:
                    raise ParserError("report exceeds max_findings limit")
        except ijson.JSONError as exc:
            raise ParserError(f"malformed generic JSON: {type(exc).__name__}") from None
