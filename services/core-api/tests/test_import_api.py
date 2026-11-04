"""Tests for the synchronous POST /api/v1/import path (Phase 2)."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kata_core_api.app import create_app
from kata_core_api.deps import get_session
from kata_domain.models import ScannerConfig

GENERIC_REPORT = {
    "schema": "kata-generic-v1",
    "findings": [
        {"title": "Hardcoded secret", "severity": "critical",
         "component": {"name": "app/config.py", "version": ""}},
        {"title": "Outdated requests", "severity": "medium",
         "vuln_ids": ["CVE-2018-18074"], "component": {"name": "requests", "version": "2.19.1"}},
    ],
}


@pytest.fixture
def client(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("KATA_DEV_AUTH", "true")

    def _session_override() -> Iterator[Session]:
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = _session_override
    with TestClient(app, headers={"X-Kata-Dev-User": "tester"}) as c:
        yield c


def _setup_engagement(client: TestClient, db: Session, scanner_key: str = "generic") -> int:
    """Create a product + engagement and ensure the scanner_config row exists; return eng id."""
    pt = client.post("/api/v1/product-types", json={"name": "imp-pt"}).json()
    product = client.post(
        "/api/v1/products", json={"product_type_id": pt["id"], "name": "imp-product"}
    ).json()
    eng = client.post(
        f"/api/v1/products/{product['id']}/engagements", json={"name": "ci"}
    ).json()
    if db.get(ScannerConfig, scanner_key) is None:
        db.add(
            ScannerConfig(
                scanner_key=scanner_key, display_name=scanner_key,
                dedup_algorithm="hash_code", hash_fields=["title"],
                reimport_algorithm="hash_code", reimport_hash_fields=["title"],
            )
        )
        db.flush()
    return int(eng["id"])


def test_import_generic_creates_findings_and_history(client: TestClient, db: Session) -> None:
    eng_id = _setup_engagement(client, db)
    payload = json.dumps(GENERIC_REPORT).encode()

    resp = client.post(
        "/api/v1/import",
        data={"engagement_id": eng_id, "scanner_key": "generic", "title": "nightly"},
        files={"file": ("report.json", payload, "application/json")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created_count"] == 2
    assert body["import_job_id"]
    test_id = body["test_id"]

    # Findings are queryable scoped to the test.
    page = client.get(f"/api/v1/findings?test_id={test_id}").json()
    assert {f["title"] for f in page["items"]} == {"Hardcoded secret", "Outdated requests"}
    assert {f["severity"] for f in page["items"]} == {"critical", "medium"}

    # Test page shows import history.
    detail = client.get(f"/api/v1/tests/{test_id}").json()
    assert detail["scanner_key"] == "generic"
    assert len(detail["imports"]) == 1
    imp = detail["imports"][0]
    assert imp["kind"] == "import" and imp["created_count"] == 2
    assert imp["import_job_id"] == body["import_job_id"]


def test_import_unknown_scanner_is_422(client: TestClient, db: Session) -> None:
    eng_id = _setup_engagement(client, db)
    resp = client.post(
        "/api/v1/import",
        data={"engagement_id": eng_id, "scanner_key": "does-not-exist"},
        files={"file": ("r.json", b'{"findings": []}', "application/json")},
    )
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_import_malformed_report_is_422(client: TestClient, db: Session) -> None:
    eng_id = _setup_engagement(client, db)
    resp = client.post(
        "/api/v1/import",
        data={"engagement_id": eng_id, "scanner_key": "generic"},
        files={"file": ("r.json", b'{"findings": [ this is not json', "application/json")},
    )
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_import_oversize_is_413(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KATA_IMPORT_MAX_BYTES", "16")  # anything real exceeds this
    eng_id = _setup_engagement(client, db)
    payload = json.dumps(GENERIC_REPORT).encode()
    resp = client.post(
        "/api/v1/import",
        data={"engagement_id": eng_id, "scanner_key": "generic"},
        files={"file": ("report.json", payload, "application/json")},
    )
    assert resp.status_code == 413
    assert resp.headers["content-type"].startswith("application/problem+json")


TRIVY_REPORT = {
    "SchemaVersion": 2,
    "Results": [
        {
            "Target": "alpine:3.19 (alpine 3.19.1)",
            "Vulnerabilities": [
                {"VulnerabilityID": "CVE-2024-0001", "PkgName": "openssl",
                 "InstalledVersion": "3.1.4-r5", "FixedVersion": "3.1.4-r6",
                 "Severity": "HIGH", "Description": "flaw"},
            ],
        }
    ],
}

KUBESCAPE_REPORT = {
    "summaryDetails": {"controls": {"C-0016": {"name": "Allow privilege escalation",
                                               "scoreFactor": 7.0}}},
    "results": [
        {"resourceID": "apps/v1/default/Deployment/nginx",
         "controls": [{"controlID": "C-0016", "name": "Allow privilege escalation",
                       "scoreFactor": 7.0, "status": {"status": "failed"}}]},
    ],
}


def test_import_trivy_end_to_end(client: TestClient, db: Session) -> None:
    eng_id = _setup_engagement(client, db, scanner_key="trivy")
    resp = client.post(
        "/api/v1/import",
        data={"engagement_id": eng_id, "scanner_key": "trivy"},
        files={"file": ("trivy.json", json.dumps(TRIVY_REPORT).encode(), "application/json")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["created_count"] == 1


def test_import_kubescape_end_to_end(client: TestClient, db: Session) -> None:
    eng_id = _setup_engagement(client, db, scanner_key="kubescape")
    resp = client.post(
        "/api/v1/import",
        data={"engagement_id": eng_id, "scanner_key": "kubescape"},
        files={"file": ("ks.json", json.dumps(KUBESCAPE_REPORT).encode(), "application/json")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["created_count"] == 1


def test_import_engagement_404(client: TestClient, db: Session) -> None:
    resp = client.post(
        "/api/v1/import",
        data={"engagement_id": 999999, "scanner_key": "generic"},
        files={"file": ("r.json", b'{"findings": []}', "application/json")},
    )
    assert resp.status_code == 404
