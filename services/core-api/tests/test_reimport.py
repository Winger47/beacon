"""Integration tests for Phase 3: dedup, the reimport diff, and the mass-closure breaker.

Skips when no database is reachable (same policy as the other integration tests). Exercises
create/untouched/reactivate/close, human-triaged protection, do_not_reactivate, within-report
dedup, and the NEEDS_CONFIRMATION confirm/reject flow (ADR-0012/0013).
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from kata_core_api.app import create_app
from kata_core_api.deps import get_session
from kata_domain.models import ScannerConfig


@pytest.fixture
def client(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("KATA_DEV_AUTH", "true")

    def _session_override() -> Iterator[Session]:
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = _session_override
    with TestClient(app, headers={"X-Kata-Dev-User": "tester"}) as c:
        yield c


def _ensure_generic(db: Session) -> None:
    if db.get(ScannerConfig, "generic") is None:
        db.add(
            ScannerConfig(
                scanner_key="generic", display_name="generic",
                dedup_algorithm="hash_code",
                hash_fields=["vuln_ids", "title", "file_path", "component_name"],
                reimport_algorithm="hash_code",
                reimport_hash_fields=["vuln_ids", "title", "file_path", "component_name"],
            )
        )
        db.flush()


def _engagement(client: TestClient, db: Session) -> int:
    _ensure_generic(db)
    pt = client.post("/api/v1/product-types", json={"name": "ri-pt"}).json()
    product = client.post(
        "/api/v1/products", json={"product_type_id": pt["id"], "name": "ri-product"}
    ).json()
    eng = client.post(
        f"/api/v1/products/{product['id']}/engagements", json={"name": "ci"}
    ).json()
    return int(eng["id"])


def _report(titles: list[str]) -> bytes:
    return json.dumps(
        {"schema": "kata-generic-v1",
         "findings": [{"title": t, "severity": "high"} for t in titles]}
    ).encode()


def _import(client: TestClient, eng_id: int, titles: list[str]) -> int:
    resp = client.post(
        "/api/v1/import",
        data={"engagement_id": eng_id, "scanner_key": "generic"},
        files={"file": ("r.json", _report(titles), "application/json")},
    )
    assert resp.status_code == 201, resp.text
    return int(resp.json()["test_id"])


def _reimport(client: TestClient, test_id: int, titles: list[str], **form: object) -> dict:
    data: dict[str, object] = {"test_id": test_id, **form}
    resp = client.post(
        "/api/v1/reimport",
        data=data,
        files={"file": ("r.json", _report(titles), "application/json")},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _statuses(client: TestClient, test_id: int) -> dict[str, str]:
    page = client.get(f"/api/v1/findings?test_id={test_id}&limit=1000").json()
    return {f["title"]: f["status"] for f in page["items"]}


def test_reimport_create_untouched_close(client: TestClient, db: Session) -> None:
    eng = _engagement(client, db)
    test_id = _import(client, eng, ["A", "B", "C"])
    # v2: A,B stay; C dropped; D new.
    body = _reimport(client, test_id, ["A", "B", "D"])
    assert body["status"] == "completed"
    assert body["created"] == 1          # D
    assert body["untouched"] == 2        # A, B
    assert body["closed"] == 1           # C
    statuses = _statuses(client, test_id)
    assert statuses["A"] == "active" and statuses["B"] == "active"
    assert statuses["C"] == "mitigated"
    assert statuses["D"] == "active"


def test_reimport_reactivates_closed_finding(client: TestClient, db: Session) -> None:
    eng = _engagement(client, db)
    test_id = _import(client, eng, ["A", "B"])
    _reimport(client, test_id, ["A"])                 # B closed
    assert _statuses(client, test_id)["B"] == "mitigated"
    body = _reimport(client, test_id, ["A", "B"])     # B returns
    assert body["reactivated"] == 1
    assert _statuses(client, test_id)["B"] == "active"


def test_do_not_reactivate_keeps_closed(client: TestClient, db: Session) -> None:
    eng = _engagement(client, db)
    test_id = _import(client, eng, ["A", "B"])
    _reimport(client, test_id, ["A"])                 # B closed
    body = _reimport(client, test_id, ["A", "B"], do_not_reactivate=True)
    assert body["reactivated"] == 0
    assert _statuses(client, test_id)["B"] == "mitigated"


def test_human_triaged_never_auto_closed(client: TestClient, db: Session) -> None:
    eng = _engagement(client, db)
    test_id = _import(client, eng, ["A", "B"])
    # Human marks B false_positive.
    page = client.get(f"/api/v1/findings?test_id={test_id}&limit=1000").json()
    b_id = next(f["id"] for f in page["items"] if f["title"] == "B")
    client.post(f"/api/v1/findings/{b_id}/transitions", json={"to_status": "false_positive"})
    # Reimport without B: it must NOT be closed.
    _reimport(client, test_id, ["A"])
    assert _statuses(client, test_id)["B"] == "false_positive"


def test_within_report_duplicate_marks_one_duplicate(client: TestClient, db: Session) -> None:
    eng = _engagement(client, db)
    # Two identical findings -> same match_key; same-tool dedup points the newer at the older.
    test_id = _import(client, eng, ["Dup", "Dup", "Unique"])
    dupes = db.execute(
        text("SELECT count(*) FROM core.finding WHERE test_id=:t AND duplicate_of IS NOT NULL"),
        {"t": test_id},
    ).scalar_one()
    assert dupes == 1


def test_mass_closure_breaker_pauses_then_confirm(client: TestClient, db: Session) -> None:
    eng = _engagement(client, db)
    titles = [f"F{i}" for i in range(12)]
    test_id = _import(client, eng, titles)
    # Reimport with only 2 -> would close 10/12 (>50%) from a report of 2 (<50% of 12): pause.
    body = _reimport(client, test_id, titles[:2])
    assert body["status"] == "needs_confirmation"
    assert body["closed"] == 0
    assert body["close_candidates"] == 10
    # Nothing closed yet.
    assert sum(1 for s in _statuses(client, test_id).values() if s == "mitigated") == 0
    # Confirm -> the 10 close.
    job = body["import_job_id"]
    conf = client.post(f"/api/v1/reimport/{job}/confirm")
    assert conf.status_code == 200, conf.text
    assert conf.json()["closed"] == 10
    assert sum(1 for s in _statuses(client, test_id).values() if s == "mitigated") == 10


def test_mass_closure_breaker_reject_keeps_active(client: TestClient, db: Session) -> None:
    eng = _engagement(client, db)
    titles = [f"G{i}" for i in range(12)]
    test_id = _import(client, eng, titles)
    body = _reimport(client, test_id, titles[:2])
    assert body["status"] == "needs_confirmation"
    job = body["import_job_id"]
    rej = client.post(f"/api/v1/reimport/{job}/reject")
    assert rej.status_code == 200, rej.text
    assert sum(1 for s in _statuses(client, test_id).values() if s == "mitigated") == 0
