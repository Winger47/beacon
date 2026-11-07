"""HTTP routes for core-api. Route handlers stay thin: they delegate to kata_domain
repositories and the transition() service (CLAUDE.md #5). No business logic here."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from kata_domain import repositories as repo
from kata_domain.enums import ActorType, FindingStatus, Role, Severity
from kata_domain.models import Engagement, ProductType
from kata_domain.reimport import BreakerConfig, confirm_reimport, reject_reimport
from kata_domain.repositories import Principal
from kata_domain.transition import transition
from kata_parsers import ParserError

from . import auth, importer, schemas
from .config import get_settings
from .deps import get_principal, get_session
from .errors import ProblemError
from .importer import ImportTooLarge

router = APIRouter(prefix="/api/v1")


def _require_global(principal: Principal, required: Role) -> None:
    if principal.global_role is None or not principal.global_role.satisfies(required):
        raise ProblemError(
            status=403,
            title="Forbidden",
            detail=f"Requires global role '{required.value}' or higher.",
            type_="https://kata.dev/problems/forbidden",
        )


def _require_product_role(
    session: Session, principal: Principal, product_id: int, required: Role
) -> None:
    role = repo.effective_role(session, principal, product_id)
    if role is None or not role.satisfies(required):
        # Do not leak existence: if they cannot even read it, 404.
        if role is None:
            raise ProblemError(
                status=404, title="Not Found", detail="Resource not found.",
                type_="https://kata.dev/problems/not-found",
            )
        raise ProblemError(
            status=403, title="Forbidden",
            detail=f"Requires role '{required.value}' or higher on this product.",
            type_="https://kata.dev/problems/forbidden",
        )


# ---------------------------------------------------------------- product types
@router.get("/product-types", response_model=list[schemas.ProductTypeOut])
def list_product_types(
    principal: Principal = Depends(get_principal), session: Session = Depends(get_session)
) -> object:
    return list(session.scalars(select(ProductType).order_by(ProductType.id)).all())


@router.post("/product-types", response_model=schemas.ProductTypeOut, status_code=201)
def create_product_type(
    body: schemas.ProductTypeIn,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> object:
    _require_global(principal, Role.MAINTAINER)
    return repo.create_product_type(session, name=body.name)


# --------------------------------------------------------------------- products
@router.get("/products", response_model=list[schemas.ProductOut])
def list_products(
    principal: Principal = Depends(get_principal), session: Session = Depends(get_session)
) -> object:
    return list(repo.list_products(session, principal))


@router.post("/products", response_model=schemas.ProductOut, status_code=201)
def create_product(
    body: schemas.ProductIn,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> object:
    _require_global(principal, Role.MAINTAINER)
    return repo.create_product(session, product_type_id=body.product_type_id, name=body.name)


@router.get("/products/{product_id}", response_model=schemas.ProductOut)
def get_product(
    product_id: int,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> object:
    no_access = (
        repo.effective_role(session, principal, product_id) is None
        and not principal.can_read_all_products
    )
    if no_access:
        raise ProblemError(
            status=404, title="Not Found", detail="Resource not found.",
            type_="https://kata.dev/problems/not-found",
        )
    product = repo.get_product(session, product_id)
    if product is None:
        raise ProblemError(
            status=404, title="Not Found", detail="Resource not found.",
            type_="https://kata.dev/problems/not-found",
        )
    return product


# ------------------------------------------------------------------ engagements
@router.post(
    "/products/{product_id}/engagements", response_model=schemas.EngagementOut, status_code=201
)
def create_engagement(
    product_id: int,
    body: schemas.EngagementIn,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> object:
    _require_product_role(session, principal, product_id, Role.WRITER)
    return repo.create_engagement(
        session, product_id=product_id, name=body.name, engagement_type=body.engagement_type
    )


# ------------------------------------------------------------------------- tests
@router.post(
    "/engagements/{engagement_id}/tests", response_model=schemas.TestOut, status_code=201
)
def create_test(
    engagement_id: int,
    body: schemas.TestIn,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> object:
    engagement = session.get(Engagement, engagement_id)
    if engagement is None:
        raise ProblemError(
            status=404, title="Not Found", detail="Resource not found.",
            type_="https://kata.dev/problems/not-found",
        )
    _require_product_role(session, principal, engagement.product_id, Role.WRITER)
    return repo.create_test(
        session, engagement_id=engagement_id, scanner_key=body.scanner_key, title=body.title
    )


def _load_engagement_or_404(session: Session, engagement_id: int) -> Engagement:
    engagement = session.get(Engagement, engagement_id)
    if engagement is None:
        raise ProblemError(
            status=404, title="Not Found", detail="Resource not found.",
            type_="https://kata.dev/problems/not-found",
        )
    return engagement


@router.get("/engagements/{engagement_id}/tests", response_model=list[schemas.TestOut])
def list_tests(
    engagement_id: int,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> object:
    engagement = _load_engagement_or_404(session, engagement_id)
    _require_product_role(session, principal, engagement.product_id, Role.READER)
    return repo.list_tests(session, engagement_id=engagement_id)


@router.get("/tests/{test_id}", response_model=schemas.TestDetailOut)
def get_test(
    test_id: int,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> object:
    test = repo.get_test(session, test_id)
    if test is None:
        raise ProblemError(
            status=404, title="Not Found", detail="Resource not found.",
            type_="https://kata.dev/problems/not-found",
        )
    engagement = _load_engagement_or_404(session, test.engagement_id)
    _require_product_role(session, principal, engagement.product_id, Role.READER)
    imports = repo.list_test_imports(session, test_id=test_id)
    pending = repo.list_pending_decisions(session, test_id=test_id)
    return schemas.TestDetailOut(
        id=test.id,
        engagement_id=test.engagement_id,
        scanner_key=test.scanner_key,
        title=test.title,
        imports=[schemas.TestImportOut.model_validate(i) for i in imports],
        pending_decisions=[schemas.ReimportDecisionOut.model_validate(d) for d in pending],
    )


# ------------------------------------------------------------------------- import
@router.post("/import", response_model=schemas.ImportResultOut, status_code=201)
def import_report(
    engagement_id: int = Form(...),
    scanner_key: str = Form(...),
    title: str | None = Form(default=None),
    file: UploadFile = File(...),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> schemas.ImportResultOut:
    """Synchronous, size-capped import (Phase 2). Parses the report into a new Test's findings
    in the request transaction. Large uploads and the async job state machine are Phase 4."""
    engagement = _load_engagement_or_404(session, engagement_id)
    _require_product_role(session, principal, engagement.product_id, Role.WRITER)

    try:
        result = importer.import_scan(
            session,
            engagement=engagement,
            scanner_key=scanner_key,
            stream=file.file,
            title=title,
            max_bytes=get_settings().import_max_bytes,
        )
    except ImportTooLarge as exc:
        raise ProblemError(
            status=413, title="Payload Too Large", detail=str(exc),
            type_="https://kata.dev/problems/import-too-large",
        ) from exc
    except ParserError as exc:
        # ParserError messages are crafted to be safe to show (never raw report content).
        raise ProblemError(
            status=422, title="Unprocessable report", detail=str(exc),
            type_="https://kata.dev/problems/parser-error",
        ) from exc

    return schemas.ImportResultOut(
        test_id=result.test_id,
        import_job_id=result.import_job_id,
        created_count=result.created_count,
    )


def _breaker_config() -> BreakerConfig:
    s = get_settings()
    return BreakerConfig(
        close_ratio=s.close_ratio,
        prev_ratio=s.close_prev_ratio,
        min_findings=s.close_min_findings,
    )


@router.post("/reimport", response_model=schemas.ReimportResultOut, status_code=201)
def reimport_report(
    test_id: int = Form(...),
    file: UploadFile = File(...),
    close_old_findings: bool = Form(default=True),
    do_not_reactivate: bool = Form(default=False),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> schemas.ReimportResultOut:
    """Reimport a report into an existing Test, diffing against its findings (Phase 3, 3.7.4).

    Uses the Test's own scanner. A mass-closure that looks like a truncated report pauses to
    ``needs_confirmation`` (resolve via /reimport/{job_id}/confirm|reject)."""
    test = repo.get_test(session, test_id)
    if test is None:
        raise ProblemError(
            status=404, title="Not Found", detail="Resource not found.",
            type_="https://kata.dev/problems/not-found",
        )
    engagement = _load_engagement_or_404(session, test.engagement_id)
    _require_product_role(session, principal, engagement.product_id, Role.WRITER)

    try:
        outcome = importer.reimport_scan(
            session,
            test=test,
            stream=file.file,
            close_old_findings=close_old_findings,
            do_not_reactivate=do_not_reactivate,
            actor_id=str(principal.user_id),
            max_bytes=get_settings().import_max_bytes,
            breaker=_breaker_config(),
        )
    except ImportTooLarge as exc:
        raise ProblemError(
            status=413, title="Payload Too Large", detail=str(exc),
            type_="https://kata.dev/problems/import-too-large",
        ) from exc
    except ParserError as exc:
        raise ProblemError(
            status=422, title="Unprocessable report", detail=str(exc),
            type_="https://kata.dev/problems/parser-error",
        ) from exc

    return schemas.ReimportResultOut(
        status=outcome.status,
        import_job_id=outcome.import_job_id,
        created=outcome.created,
        reactivated=outcome.reactivated,
        untouched=outcome.untouched,
        closed=outcome.closed,
        close_candidates=outcome.close_candidates,
    )


def _load_decision_or_404(session: Session, principal: Principal, job_id: str) -> object:
    decision = repo.get_reimport_decision(session, job_id)
    if decision is None:
        raise ProblemError(
            status=404, title="Not Found", detail="Resource not found.",
            type_="https://kata.dev/problems/not-found",
        )
    test = repo.get_test(session, decision.test_id)
    engagement = _load_engagement_or_404(session, test.engagement_id) if test else None
    if engagement is None:
        raise ProblemError(
            status=404, title="Not Found", detail="Resource not found.",
            type_="https://kata.dev/problems/not-found",
        )
    _require_product_role(session, principal, engagement.product_id, Role.WRITER)
    return decision


@router.post("/reimport/{job_id}/confirm", response_model=schemas.ReimportResultOut)
def confirm_reimport_decision(
    job_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> schemas.ReimportResultOut:
    """Apply a paused mass closure after human review (ADR-0013)."""
    decision = _load_decision_or_404(session, principal, job_id)
    closed = confirm_reimport(session, decision=decision, actor_id=str(principal.user_id))  # type: ignore[arg-type]
    return schemas.ReimportResultOut(
        status="completed", import_job_id=job_id,
        created=0, reactivated=0, untouched=0, closed=closed, close_candidates=0,
    )


@router.post("/reimport/{job_id}/reject", response_model=schemas.ReimportResultOut)
def reject_reimport_decision(
    job_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> schemas.ReimportResultOut:
    """Discard a paused mass closure: nothing closes (ADR-0013)."""
    decision = _load_decision_or_404(session, principal, job_id)
    reject_reimport(session, decision=decision)  # type: ignore[arg-type]
    return schemas.ReimportResultOut(
        status="rejected", import_job_id=job_id,
        created=0, reactivated=0, untouched=0, closed=0, close_candidates=0,
    )


# ---------------------------------------------------------------------- findings
@router.get("/findings", response_model=schemas.FindingPageOut)
def list_findings(
    product_id: int | None = None,
    test_id: int | None = None,
    status: FindingStatus | None = None,
    severity: Severity | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    cursor: str | None = None,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> schemas.FindingPageOut:
    try:
        page = repo.list_findings(
            session, principal, product_id=product_id, test_id=test_id, status=status,
            severity=severity, limit=limit, cursor=cursor,
        )
    except ValueError as exc:  # invalid cursor
        raise ProblemError(
            status=400, title="Invalid cursor", detail=str(exc),
            type_="https://kata.dev/problems/invalid-cursor",
        ) from exc
    return schemas.FindingPageOut(
        items=[schemas.FindingOut.model_validate(f) for f in page.findings],
        next_cursor=page.next_cursor,
    )


@router.get("/findings/{finding_id}", response_model=schemas.FindingOut)
def get_finding(
    finding_id: int,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> object:
    finding = repo.get_finding_authorized(session, principal, finding_id)
    if finding is None:
        raise ProblemError(
            status=404, title="Not Found", detail="Resource not found.",
            type_="https://kata.dev/problems/not-found",
        )
    return finding


@router.post("/findings/{finding_id}/transitions", response_model=schemas.FindingOut)
def transition_finding(
    finding_id: int,
    body: schemas.TransitionIn,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> object:
    finding = repo.get_finding_authorized(session, principal, finding_id)
    if finding is None:
        raise ProblemError(
            status=404, title="Not Found", detail="Resource not found.",
            type_="https://kata.dev/problems/not-found",
        )
    _require_product_role(session, principal, finding.product_id, Role.WRITER)
    transition(
        session, finding, body.to_status,
        actor_type=ActorType.USER, actor_id=str(principal.user_id), reason=body.reason,
    )
    return finding


# --------------------------------------------------------------------- api tokens
@router.post("/api-tokens", response_model=schemas.ApiTokenCreatedOut, status_code=201)
def create_api_token(
    body: schemas.ApiTokenIn,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> schemas.ApiTokenCreatedOut:
    token, secret = auth.create_api_token(
        session, user_id=principal.user_id, name=body.name,
        scope_product_ids=body.scope_product_ids, scope_actions=body.scope_actions,
        expires_at=body.expires_at,
    )
    return schemas.ApiTokenCreatedOut(
        token=schemas.ApiTokenOut.model_validate(token), secret=secret
    )


@router.get("/api-tokens", response_model=list[schemas.ApiTokenOut])
def list_api_tokens(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> object:
    return list(repo.list_api_tokens(session, principal.user_id))


@router.delete("/api-tokens/{token_id}", status_code=204)
def revoke_api_token(
    token_id: int,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> None:
    if not repo.revoke_api_token(session, user_id=principal.user_id, token_id=token_id):
        raise ProblemError(
            status=404, title="Not Found", detail="Token not found.",
            type_="https://kata.dev/problems/not-found",
        )
