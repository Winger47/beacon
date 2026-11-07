"""Deterministic Trivy-format report generation for the parity harness.

A finding's dedup identity under the ``trivy`` scanner config is ``hash_code`` over
``[vuln_ids, component_name, component_version]`` (seed.py / ADR-0011). So one Vuln here, a
(CVE, package, version) triple, is exactly one finding. Generation is pure and ordered, so the
same ``Vuln`` set always serializes to byte-identical JSON — the harness is reproducible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Vuln:
    """One Trivy vulnerability == one finding. ``key`` is the dedup identity the oracle tracks."""

    cve: str
    pkg: str
    version: str
    severity: str = "HIGH"

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.cve, self.pkg, self.version)


def build_report(vulns: list[Vuln], *, artifact: str = "alpine:3.19") -> bytes:
    """Serialize ``vulns`` into a minimal but valid Trivy JSON report (SchemaVersion 2)."""
    rows = [
        {
            "VulnerabilityID": v.cve,
            "PkgName": v.pkg,
            "InstalledVersion": v.version,
            "FixedVersion": "",
            "Severity": v.severity,
            "Title": f"{v.cve} in {v.pkg}",
            "Description": f"{v.cve} affects {v.pkg} {v.version}",
            "PrimaryURL": f"https://avd.aquasec.com/nvd/{v.cve.lower()}",
        }
        for v in vulns
    ]
    report = {
        "SchemaVersion": 2,
        "ArtifactName": artifact,
        "ArtifactType": "container_image",
        "Results": [
            {
                "Target": f"{artifact} (alpine 3.19.9)",
                "Class": "os-pkgs",
                "Type": "alpine",
                "Vulnerabilities": rows,
            }
        ],
    }
    return json.dumps(report, indent=2, sort_keys=True).encode("utf-8")
