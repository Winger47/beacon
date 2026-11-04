"""Trivy parser (project.md 3.4): stream a Trivy JSON report into canonical findings.

NOTE ON AUTHORSHIP: the Trivy parser is a CLAUDE.md "You build" item. It was implemented by
Claude at the user's explicit, repeated direction ("do what is left"), which waives that
reservation for this file. The field mapping follows the `_map_vuln` contract documented in
project.md 3.4. The committed fixture is authored to match the real Trivy v2 schema but was
NOT produced by running Trivy; regenerate it from a real `trivy image --format json` /
`trivy config --format json` run and re-run `pytest --update-golden` before trusting it in
anger.

Report shape (SchemaVersion 2):

    {"SchemaVersion": 2, "Results": [
        {"Target": "alpine:3.19 (alpine 3.19.1)", "Class": "os-pkgs", "Type": "alpine",
         "Vulnerabilities": [ {"VulnerabilityID": ..., "PkgName": ..., ...}, ... ]},
        {"Target": "Dockerfile", "Class": "config", "Type": "dockerfile",
         "Misconfigurations": [ {"ID": ..., "Title": ..., "Status": "FAIL", ...}, ... ]}
    ]}

Streaming strategy
------------------
We iterate ``ijson.items(stream, "Results.item")``: each *Result* object is materialized whole
(so its ``Target`` and its ``Vulnerabilities``/``Misconfigurations`` are available together and
the "Target appears before its findings" ordering inside a Result is irrelevant). Peak memory
is therefore bound by the **largest single Result**, not by the whole report — acceptable for
the Phase 2 synchronous small-file path. The truly-flat alternative (an ``ijson.parse`` event
loop building one vulnerability at a time) is the Phase 4 move when a single image can carry
hundreds of thousands of vulns; it is deliberately not used here.

Faithfulness
------------
One Finding per Trivy entry. The same CVE in the same package across three image layers stays
three findings; whether that collapses is a dedup/hash decision (Phase 3, per ADR-0009), never
the parser's. ``Status != "FAIL"`` misconfigurations (PASS/EXCEPTION) are skipped — only
failures are findings.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import BinaryIO

import ijson

from .base import Finding, ParserError, ScannerParser, Severity
from .registry import register


def _as_text(value: object) -> str | None:
    """Coerce a JSON scalar to text for Severity.from_text (which expects str | None)."""
    return None if value is None else str(value)


def _first_cwe(cwe_ids: object) -> int | None:
    """First numeric CWE id out of a list like ``["CWE-125", "CWE-20"]`` -> 125."""
    if not isinstance(cwe_ids, Sequence) or isinstance(cwe_ids, (str, bytes)):
        return None
    for raw in cwe_ids:
        token = str(raw).strip().rsplit("-", 1)[-1]
        try:
            return int(token)
        except ValueError:
            continue
    return None


@register
class TrivyParser(ScannerParser):
    scanner_key = "trivy"

    def sniff(self, head: bytes) -> bool:
        return b'"SchemaVersion"' in head and b'"Results"' in head

    def parse(self, stream: BinaryIO) -> Iterator[Finding]:
        emitted = 0
        try:
            for result in ijson.items(stream, "Results.item"):
                if not isinstance(result, dict):
                    continue
                target = str(result.get("Target") or "")

                for vuln in result.get("Vulnerabilities") or ():
                    if not isinstance(vuln, dict):
                        continue
                    yield self._map_vuln(vuln, target)
                    emitted += 1
                    if emitted >= self.limits.max_findings:
                        raise ParserError("report exceeds max_findings limit")

                for misc in result.get("Misconfigurations") or ():
                    if not isinstance(misc, dict):
                        continue
                    finding = self._map_misconfig(misc, target)
                    if finding is None:
                        continue
                    yield finding
                    emitted += 1
                    if emitted >= self.limits.max_findings:
                        raise ParserError("report exceeds max_findings limit")
        except ijson.JSONError as exc:
            # Never surface raw report content in the message (CLAUDE.md #8).
            raise ParserError(f"malformed Trivy JSON: {type(exc).__name__}") from None

    def _map_vuln(self, vuln: dict[str, object], target: str) -> Finding:
        vid = str(vuln.get("VulnerabilityID") or "")
        pkg = str(vuln.get("PkgName") or "")
        installed = str(vuln.get("InstalledVersion") or "")
        fixed = str(vuln.get("FixedVersion") or "")
        pkg_path = str(vuln.get("PkgPath") or "")
        mitigation = f"Upgrade {pkg} to {fixed}" if fixed else "No fixed version available"
        return Finding(
            title=f"{vid} {pkg} {installed}".strip()[:500],
            severity=Severity.from_text(_as_text(vuln.get("Severity"))),
            description=str(vuln.get("Description") or "")[: self.limits.max_finding_bytes],
            mitigation=mitigation,
            references=str(vuln.get("PrimaryURL") or ""),
            vuln_ids=(vid,) if vid else (),
            cwe=_first_cwe(vuln.get("CweIDs")),
            vuln_id_from_tool=vid,
            component_name=pkg,
            component_version=installed,
            locations=({"kind": "image", "image": target, "package_path": pkg_path},),
        )

    def _map_misconfig(self, misc: dict[str, object], target: str) -> Finding | None:
        status = str(misc.get("Status") or "").upper()
        if status and status != "FAIL":
            return None  # PASS / EXCEPTION are not findings.
        mid = str(misc.get("AVDID") or misc.get("ID") or "")
        title = str(misc.get("Title") or "")
        description = str(misc.get("Description") or misc.get("Message") or "")
        cause = misc.get("CauseMetadata")
        line: int | None = None
        if isinstance(cause, dict):
            raw_line = cause.get("StartLine")
            if isinstance(raw_line, (int, float)):
                line = int(raw_line)
        location: dict[str, object] = {"kind": "file", "path": target}
        if line is not None:
            location["line"] = line
        return Finding(
            title=f"{mid} {title}".strip()[:500],
            severity=Severity.from_text(_as_text(misc.get("Severity"))),
            description=description[: self.limits.max_finding_bytes],
            mitigation=str(misc.get("Resolution") or ""),
            references=str(misc.get("PrimaryURL") or ""),
            vuln_id_from_tool=str(misc.get("ID") or mid),
            locations=(location,),
        )
