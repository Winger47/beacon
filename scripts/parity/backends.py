"""Backend drivers for the parity harness: Kata (always) and DefectDojo (optional).

Both expose the same tiny interface — ``bootstrap()`` then ``run_step()`` per sequence step —
so the runner is backend-agnostic. The Kata driver speaks Kata's HTTP API with local dev auth
(``KATA_DEV_AUTH=true``). The DefectDojo driver speaks its documented REST API v2
(import-scan / reimport-scan) and is skipped unless ``DEFECTDOJO_URL`` + ``DEFECTDOJO_TOKEN``
are set; it uses DefectDojo only as a behavioral reference over the wire (never its code).
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx

from .scenario import Counts, Step
from .trivy_report import build_report

_TIMEOUT = httpx.Timeout(30.0)


class Backend(Protocol):
    name: str

    def bootstrap(self) -> None: ...

    def run_step(self, step: Step) -> Counts: ...


class KataBackend:
    """Drives Kata's in-process import/reimport over HTTP (project.md 3.5-3.7)."""

    name = "kata"

    def __init__(self, base_url: str, *, dev_user: str, scanner: str = "trivy") -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-Kata-Dev-User": dev_user},
            timeout=_TIMEOUT,
        )
        self._scanner = scanner
        self._test_id: int | None = None

    def bootstrap(self) -> None:
        pt = self._post_json("/api/v1/product-types", {"name": "parity"})
        product = self._post_json(
            "/api/v1/products", {"product_type_id": pt["id"], "name": f"parity-{os.getpid()}"}
        )
        eng = self._post_json(
            f"/api/v1/products/{product['id']}/engagements", {"name": "parity-run"}
        )
        self._engagement_id = int(eng["id"])

    def run_step(self, step: Step) -> Counts:
        report = build_report(step.vulns)
        files = {"file": ("report.json", report, "application/json")}
        if step.kind == "import":
            data = {
                "engagement_id": str(self._engagement_id),
                "scanner_key": self._scanner,
                "title": step.label,
            }
            res = self._post_form("/api/v1/import", data=data, files=files)
            self._test_id = int(res["test_id"])
            return Counts(created=int(res["created_count"]))

        assert self._test_id is not None, "reimport before import"
        data = {
            "test_id": str(self._test_id),
            "close_old_findings": str(step.close_old_findings).lower(),
            "do_not_reactivate": str(step.do_not_reactivate).lower(),
        }
        res = self._post_form("/api/v1/reimport", data=data, files=files)
        return Counts(
            created=int(res["created"]),
            untouched=int(res["untouched"]),
            reactivated=int(res["reactivated"]),
            closed=int(res["closed"]),
        )

    def _post_json(self, path: str, body: dict[str, object]) -> dict[str, object]:
        resp = self._client.post(path, json=body)
        resp.raise_for_status()
        return dict(resp.json())

    def _post_form(
        self, path: str, *, data: dict[str, str], files: dict[str, object]
    ) -> dict[str, object]:
        resp = self._client.post(path, data=data, files=files)
        resp.raise_for_status()
        return dict(resp.json())


class DefectDojoBackend:
    """Drives a live DefectDojo via REST API v2. Reference oracle only; never its code.

    Mapping to the four counts (DefectDojo reimport-scan ``statistics``):
      created     <- after.<sev>.created summed, or ``statistics.after`` deltas
      closed      <- findings closed this reimport
      reactivated <- findings reactivated
      untouched   <- findings left untouched
    DefectDojo has no mass-closure breaker (documented divergence, docs/parity.md).
    """

    name = "defectdojo"

    def __init__(self, base_url: str, token: str, *, scanner: str = "Trivy Scan") -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Token {token}"},
            timeout=_TIMEOUT,
        )
        self._scan_type = scanner
        self._test_id: int | None = None
        self._engagement_id: int | None = None

    @classmethod
    def from_env(cls) -> DefectDojoBackend | None:
        url = os.environ.get("DEFECTDOJO_URL")
        token = os.environ.get("DEFECTDOJO_TOKEN")
        if not url or not token:
            return None
        return cls(url, token)

    def bootstrap(self) -> None:
        # Requires a pre-created engagement id in DEFECTDOJO_ENGAGEMENT_ID (product/engagement
        # setup in DefectDojo is out of scope for this harness).
        eng = os.environ.get("DEFECTDOJO_ENGAGEMENT_ID")
        if not eng:
            raise RuntimeError("set DEFECTDOJO_ENGAGEMENT_ID to run the DefectDojo backend")
        self._engagement_id = int(eng)

    def run_step(self, step: Step) -> Counts:
        report = build_report(step.vulns)
        files = {"file": ("report.json", report, "application/json")}
        if step.kind == "import":
            data = {"scan_type": self._scan_type, "engagement": str(self._engagement_id)}
            res = self._post("/api/v2/import-scan/", data=data, files=files)
            self._test_id = int(res["test"])
            return _dd_counts(res)
        assert self._test_id is not None, "reimport before import"
        data = {
            "scan_type": self._scan_type,
            "test": str(self._test_id),
            "close_old_findings": str(step.close_old_findings).lower(),
            "do_not_reactivate": str(step.do_not_reactivate).lower(),
        }
        res = self._post("/api/v2/reimport-scan/", data=data, files=files)
        return _dd_counts(res)

    def _post(
        self, path: str, *, data: dict[str, str], files: dict[str, object]
    ) -> dict[str, object]:
        resp = self._client.post(path, data=data, files=files)
        resp.raise_for_status()
        return dict(resp.json())


def _dd_counts(res: dict[str, object]) -> Counts:
    """Best-effort map of DefectDojo's reimport response to the four counts."""
    stats = res.get("statistics")
    if not isinstance(stats, dict):
        return Counts()
    delta = stats.get("delta")
    if isinstance(delta, dict):
        return Counts(
            created=int(delta.get("created", 0)),
            reactivated=int(delta.get("reactivated", 0)),
            closed=int(delta.get("closed", 0)),
            untouched=int(delta.get("left untouched", delta.get("untouched", 0))),
        )
    return Counts()
