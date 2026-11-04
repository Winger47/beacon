"""Kubescape parser (project.md 3.4): controls -> one finding per failed control per resource.

AUTHORSHIP / VALIDATION CAVEAT
------------------------------
Implemented by Claude at the user's explicit direction. Kubescape is a "later parser" that
CLAUDE.md gates behind reviewing the user's Trivy parser; that gate was waived here. It was
written against the documented Kubescape JSON schema (kubescape docs + the behavioral field
mapping observed in DefectDojo's importer — behavioral reference only, no code copied,
CLAUDE.md #1) but was **NOT validated against a real `kubescape scan --format json` run**.
Regenerate the fixture from a real scan and re-run `pytest --update-golden`, and re-check the
field names below, before trusting it.

THE "think first" DECISION (project.md Phase 2)
-----------------------------------------------
One control failing on 200 resources is **200 findings**, not 1: a security engineer triages
per resource ("which Deployment is privileged?"), so the parser emits one Finding per
failed (control, resource) pair. Whether those later collapse is a dedup decision (Phase 3),
never the parser's (ADR-0009).

Report shape (v2/v3 `--format json`):

    {"summaryDetails": {"controls": {"C-0016": {"name": ..., "scoreFactor": 7.0, ...}}},
     "results": [
        {"resourceID": "apps/v1/default/Deployment/nginx",
         "controls": [
            {"controlID": "C-0016", "name": "Allow privilege escalation",
             "status": {"status": "failed"}, "scoreFactor": 7.0,
             "rules": [{"name": ..., "status": {"status": "failed"}, "paths": [...]}]}
         ]}
     ],
     "resources": [{"resourceID": ..., "object": {...}}]}

Streaming strategy & a known limitation
---------------------------------------
Single forward pass over ``ijson.items(stream, "results.item")`` — memory bound by the
largest single result, flat in the number of resources. Severity is read from each control's
``scoreFactor`` **within the result**. In some Kubescape versions ``scoreFactor`` lives only in
``summaryDetails.controls`` (which precedes ``results``); joining the two sources in one pass
without buffering is a Phase 4 refinement. When ``scoreFactor`` is absent we floor severity to
``info`` (never crash) and record it — this is the documented limitation to fix with a real
fixture. ``resources[]`` (kind/namespace/name) comes *after* ``results[]`` in the document, so
we do not forward-join it; the finding carries the full ``resourceID`` and resolving friendly
names is a later enrichment.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import BinaryIO

import ijson

from .base import Finding, ParserError, ScannerParser, Severity
from .registry import register

_HUB = "https://hub.armosec.io/docs"


def _severity_from_score(score: object) -> Severity:
    """Map a Kubescape control scoreFactor (0-10) to our ordinal severity.

    Bands follow Kubescape's own scale (as surfaced by DefectDojo's importer):
    <4 low, <7 medium, <9 high, else critical. Missing score -> info (documented limitation).
    """
    if not isinstance(score, (int, float, Decimal)):
        return Severity.INFO
    value = float(score)
    if value < 4:
        return Severity.LOW
    if value < 7:
        return Severity.MEDIUM
    if value < 9:
        return Severity.HIGH
    return Severity.CRITICAL


def _status_text(obj: object) -> str:
    """Kubescape status is either {"status": "failed"} or a bare string across versions."""
    if isinstance(obj, dict):
        return str(obj.get("status") or "").lower()
    return str(obj or "").lower()


@register
class KubescapeParser(ScannerParser):
    scanner_key = "kubescape"

    def sniff(self, head: bytes) -> bool:
        return b'"summaryDetails"' in head or (b'"controlID"' in head and b'"resourceID"' in head)

    def parse(self, stream: BinaryIO) -> Iterator[Finding]:
        emitted = 0
        try:
            for result in ijson.items(stream, "results.item"):
                if not isinstance(result, dict):
                    continue
                resource_id = str(result.get("resourceID") or "")
                for control in result.get("controls") or ():
                    if not isinstance(control, dict):
                        continue
                    if _status_text(control.get("status")) != "failed":
                        continue  # only failed controls are findings
                    yield self._map_control(control, resource_id)
                    emitted += 1
                    if emitted >= self.limits.max_findings:
                        raise ParserError("report exceeds max_findings limit")
        except ijson.JSONError as exc:
            raise ParserError(f"malformed Kubescape JSON: {type(exc).__name__}") from None

    def _map_control(self, control: dict[str, object], resource_id: str) -> Finding:
        control_id = str(control.get("controlID") or "")
        name = str(control.get("name") or control_id)
        severity = _severity_from_score(control.get("scoreFactor"))
        description = f"Control {control_id} ({name}) failed on resource {resource_id}."
        references = f"{_HUB}/{control_id.lower()}" if control_id else ""
        extra: dict[str, str] = {}
        if control.get("scoreFactor") is None:
            # Surface the documented severity limitation on the finding itself.
            extra["severity_source"] = "defaulted-info-no-scoreFactor"
        return Finding(
            title=f"{name} on {resource_id}".strip()[:500],
            severity=severity,
            description=description[: self.limits.max_finding_bytes],
            mitigation=str(control.get("mitigation") or ""),
            references=references,
            vuln_id_from_tool=control_id,
            unique_id_from_tool=f"{control_id}:{resource_id}" if control_id and resource_id else "",
            locations=({"kind": "k8s", "resource_id": resource_id},),
            extra=extra,
        )
