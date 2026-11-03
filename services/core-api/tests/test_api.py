"""HTTP API tests via FastAPI TestClient. Uses dev-header auth and a rollback session."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kata_core_api.app import create_app
from kata_core_api.deps import get_session
from kata_domain.enums import Severity
from kata_domain.models import Finding


@pytest.fixture
def client(db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("KATA_DEV_AUTH", "true")

    def _session_override() -> Iterator[Session]:
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = _session_override
    with TestClient(app, headers={"X-Kata-Dev-User": "tester"}) as c:
        yield c


def test_unauthorized_returns_problem_json(client: TestClient) -> None:
    resp = client.get("/api/v1/products", headers={"X-Kata-Dev-User": ""})
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 401 and body["title"] == "Unauthorized"


def test_crud_happy_path_and_keyset_shape(client: TestClient) -> None:
    pt = client.post("/api/v1/product-types", json={"name": "api-pt"}).json()
    product = client.post(
        "/api/v1/products", json={"product_type_id": pt["id"], "name": "api-product"}
    ).json()
    eng = client.post(
        f"/api/v1/products/{product['id']}/engagements", json={"name": "e"}
    ).json()
    # scanner_config must exist for the test FK; insert via the shared test session.
    from kata_domain.models import ScannerConfig

    sess = next(client.app.dependency_overrides[get_session]())  # the shared test session
    sess.add(
        ScannerConfig(
            scanner_key="apitest", display_name="t", dedup_algorithm="hash_code",
            hash_fields=["title"], reimport_algorithm="hash_code", reimport_hash_fields=["title"],
        )
    )
    sess.flush()
    test = client.post(
        f"/api/v1/engagements/{eng['id']}/tests",
        json={"scanner_key": "apitest", "title": "t"},
    ).json()

    page = client.get(f"/api/v1/findings?product_id={product['id']}").json()
    assert page == {"items": [], "next_cursor": None}
    assert test["engagement_id"] == eng["id"]


def test_transition_valid_then_invalid(client: TestClient, db: Session) -> None:
    pt = client.post("/api/v1/product-types", json={"name": "t-pt"}).json()
    product = client.post(
        "/api/v1/products", json={"product_type_id": pt["id"], "name": "t-product"}
    ).json()
    eng = client.post(f"/api/v1/products/{product['id']}/engagements", json={"name": "e"}).json()
    from kata_domain.models import ScannerConfig

    db.add(
        ScannerConfig(
            scanner_key="transtest", display_name="t", dedup_algorithm="hash_code",
            hash_fields=["title"], reimport_algorithm="hash_code", reimport_hash_fields=["title"],
        )
    )
    db.flush()
    test = client.post(
        f"/api/v1/engagements/{eng['id']}/tests", json={"scanner_key": "transtest"}
    ).json()
    finding = Finding(
        test_id=test["id"], engagement_id=eng["id"], product_id=product["id"],
        title="f", severity=Severity.HIGH,
    )
    db.add(finding)
    db.flush()

    ok = client.post(
        f"/api/v1/findings/{finding.id}/transitions",
        json={"to_status": "mitigated", "reason": "fixed"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "mitigated"

    bad = client.post(
        f"/api/v1/findings/{finding.id}/transitions", json={"to_status": "false_positive"}
    )
    assert bad.status_code == 409
    assert bad.headers["content-type"].startswith("application/problem+json")


def test_api_token_create_and_use(client: TestClient) -> None:
    created = client.post("/api/v1/api-tokens", json={"name": "ci"}).json()
    secret = created["secret"]
    assert secret.startswith("kata_")

    # Use the token (no dev header) to authenticate.
    resp = client.get(
        "/api/v1/products",
        headers={"X-Kata-Dev-User": "", "Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200


def test_non_admin_gets_404_for_inaccessible_product(client: TestClient) -> None:
    from kata_core_api.deps import get_principal
    from kata_domain.repositories import Principal

    pt = client.post("/api/v1/product-types", json={"name": "x-pt"}).json()
    product = client.post(
        "/api/v1/products", json={"product_type_id": pt["id"], "name": "x-product"}
    ).json()

    # Switch to a principal with no access to anything.
    client.app.dependency_overrides[get_principal] = lambda: Principal(
        user_id=999999, global_role=None
    )
    resp = client.get(f"/api/v1/products/{product['id']}")
    assert resp.status_code == 404  # not 403 — no existence leak (ADR-0008)
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_api_token_revoke(client: TestClient) -> None:
    created = client.post("/api/v1/api-tokens", json={"name": "ci"}).json()
    secret = created["secret"]
    token_id = created["token"]["id"]

    assert any(t["id"] == token_id for t in client.get("/api/v1/api-tokens").json())

    assert client.delete(f"/api/v1/api-tokens/{token_id}").status_code == 204

    # Revoked token no longer authenticates.
    resp = client.get(
        "/api/v1/products",
        headers={"X-Kata-Dev-User": "", "Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 401


def test_openapi_published(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/api/v1/findings" in schema["paths"]
    assert schema["info"]["title"] == "Kata core-api"
