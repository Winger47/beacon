"""Kubescape parser (project.md 3.4): controls -> one finding per failed control per resource.

AUTHORSHIP: implemented by Claude at the user's direction. Kubescape is a "later parser" that
CLAUDE.md gates behind reviewing the user's Trivy parser; that gate was waived here. Validated
against **real** `kubescape scan --format json` output (CLI v3.0.44) over a deliberately bad
manifest; the committed fixture is that output, trimmed.

THE "think first" DECISION (project.md Phase 2)
-----------------------------------------------
A control failing on 200 resources is **200 findings**, not 1: a security engineer triages per
resource ("which Deployment is privileged?"), so the parser emits one Finding per failed
(control, resource) pair. Whether those later collapse is a dedup decision (Phase 3), never the
parser's (ADR-0009).

Real report shape (v3 `--format json`)
---------------------------------------
``summaryDetails.controls`` (an object keyed by controlID) is the ONLY place that carries a
control's ``scoreFactor`` (0-10) and display ``name``; the controls embedded in ``results[]``
carry only ``controlID``, ``name``, ``status`` and ``rules`` — NOT the score. So severity must
be joined from ``summaryDetails``:

    {"summaryDetails": {"controls": {"C-0057": {"name": "Privileged container",
                                                "scoreFactor": 8.0, "status": "failed"}}},
     "results": [
        {"resourceID": "path=.../api=apps/v1/default/Deployment/nginx",
         "controls": [{"controlID": "C-0057", "name": "Privileged container",
                       "status": {"status": "failed"}, "rules": [...]}]}
     ]}

Severity (scoreFactor band, matching Kubescape's own scale): <4 low, <7 medium, <9 high, else
critical; a control with no score -> info.

Streaming strategy
------------------
Single forward pass via ``ijson.parse``. ``summaryDetails`` precedes ``results`` in the document
(verified on real output), so we accumulate the small, bounded ``summaryDetails.controls`` index
first, then rebuild each ``results[]`` item with an ``ObjectBuilder`` and emit as soon as it
closes — memory is bound by the control index plus one result object, not the whole report, and
we never seek. ``resources[]`` (kind/namespace/name) comes *after* ``results[]`` and is not
forward-joinable in one pass; the finding carries the full ``resourceID`` and friendly-name
resolution is a later enrichment.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import BinaryIO

import ijson
from ijson.common import ObjectBuilder

from .base import Finding, ParserError, ScannerParser, Severity
from .registry import register

_HUB = "https://hub.armosec.io/docs"
_SUMMARY_PREFIX = "summaryDetails.controls."


def _severity_from_score(score: object) -> Severity:
    """Map a Kubescape control scoreFactor (0-10) to our ordinal severity.

    <4 low, <7 medium, <9 high, else critical. Missing score -> info.
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
        # controlID -> {"scoreFactor": ..., "name": ..., "mitigation": ...}
        controls: dict[str, dict[str, object]] = {}
        builder: ObjectBuilder | None = None
        emitted = 0
        try:
            for prefix, event, value in ijson.parse(stream):
                if builder is None:
                    if prefix.startswith(_SUMMARY_PREFIX) and event in ("string", "number"):
                        cid, _, field = prefix[len(_SUMMARY_PREFIX) :].partition(".")
                        if field in ("scoreFactor", "name", "mitigation"):
                            controls.setdefault(cid, {})[field] = value
                    elif prefix == "results.item" and event == "start_map":
                        builder = ObjectBuilder()
                        builder.event(event, value)
                else:
                    builder.event(event, value)
                    if prefix == "results.item" and event == "end_map":
                        result = builder.value
                        builder = None
                        if isinstance(result, dict):
                            for finding in self._emit(result, controls):
                                yield finding
                                emitted += 1
                                if emitted >= self.limits.max_findings:
                                    raise ParserError("report exceeds max_findings limit")
        except ijson.JSONError as exc:
            raise ParserError(f"malformed Kubescape JSON: {type(exc).__name__}") from None

    def _emit(
        self, result: dict[str, object], controls: dict[str, dict[str, object]]
    ) -> Iterator[Finding]:
        resource_id = str(result.get("resourceID") or "")
        raw_controls = result.get("controls")
        if not isinstance(raw_controls, list):
            return
        for control in raw_controls:
            if not isinstance(control, dict):
                continue
            if _status_text(control.get("status")) != "failed":
                continue  # only failed controls are findings
            yield self._map_control(control, resource_id, controls)

    def _map_control(
        self,
        control: dict[str, object],
        resource_id: str,
        controls: dict[str, dict[str, object]],
    ) -> Finding:
        control_id = str(control.get("controlID") or "")
        summary = controls.get(control_id, {})
        name = str(control.get("name") or summary.get("name") or control_id)
        severity = _severity_from_score(summary.get("scoreFactor"))
        extra: dict[str, str] = {}
        if summary.get("scoreFactor") is None:
            extra["severity_source"] = "defaulted-info-no-scoreFactor"
        return Finding(
            title=f"{name} on {resource_id}".strip()[:500],
            severity=severity,
            description=f"Control {control_id} ({name}) failed on resource {resource_id}."[
                : self.limits.max_finding_bytes
            ],
            mitigation=str(summary.get("mitigation") or control.get("mitigation") or ""),
            references=f"{_HUB}/{control_id.lower()}" if control_id else "",
            vuln_id_from_tool=control_id,
            unique_id_from_tool=f"{control_id}:{resource_id}" if control_id and resource_id else "",
            locations=({"kind": "k8s", "resource_id": resource_id},),
            extra=extra,
        )
