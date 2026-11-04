"""Pydantic request/response schemas for the core-api HTTP layer."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict

from kata_domain.enums import FindingStatus, Severity


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- hierarchy ----
class ProductTypeIn(BaseModel):
    name: str


class ProductTypeOut(ORMModel):
    id: int
    name: str
    created_at: datetime.datetime


class ProductIn(BaseModel):
    product_type_id: int
    name: str


class ProductOut(ORMModel):
    id: int
    product_type_id: int
    name: str
    description: str | None = None


class EngagementIn(BaseModel):
    name: str
    engagement_type: str = "ci_cd"


class EngagementOut(ORMModel):
    id: int
    product_id: int
    name: str
    engagement_type: str
    status: str


class TestIn(BaseModel):
    scanner_key: str
    title: str | None = None


class TestOut(ORMModel):
    id: int
    engagement_id: int
    scanner_key: str
    title: str | None = None


class TestImportOut(ORMModel):
    id: int
    test_id: int
    import_job_id: str
    kind: str
    created_count: int
    untouched_count: int
    reactivated_count: int
    closed_count: int
    created_at: datetime.datetime


class TestDetailOut(ORMModel):
    id: int
    engagement_id: int
    scanner_key: str
    title: str | None = None
    imports: list[TestImportOut] = []


class ImportResultOut(BaseModel):
    """Result of a synchronous POST /import (Phase 2)."""

    test_id: int
    import_job_id: str
    created_count: int


# ---- findings ----
class FindingOut(ORMModel):
    id: int
    test_id: int
    product_id: int
    engagement_id: int
    title: str
    severity: Severity
    status: FindingStatus
    verified: bool
    component_id: int | None = None


class FindingPageOut(BaseModel):
    items: list[FindingOut]
    next_cursor: str | None = None


class TransitionIn(BaseModel):
    to_status: FindingStatus
    reason: str | None = None


# ---- api tokens ----
class ApiTokenIn(BaseModel):
    name: str
    scope_product_ids: list[int] = []
    scope_actions: list[str] = []
    expires_at: datetime.datetime | None = None


class ApiTokenOut(ORMModel):
    id: int
    name: str
    scope_product_ids: list[int]
    scope_actions: list[str]
    expires_at: datetime.datetime | None = None
    created_at: datetime.datetime


class ApiTokenCreatedOut(BaseModel):
    """Returned once on creation; includes the raw secret, shown only here."""

    token: ApiTokenOut
    secret: str
