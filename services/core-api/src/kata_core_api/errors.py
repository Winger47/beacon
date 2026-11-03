"""RFC 9457 (application/problem+json) error handling for core-api."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kata_domain.transition import InvalidTransition

PROBLEM_BASE = "https://kata.dev/problems"
CONTENT_TYPE = "application/problem+json"


class ProblemError(Exception):
    """Raise to return an RFC 9457 problem response."""

    def __init__(self, *, status: int, title: str, detail: str, type_: str = "about:blank") -> None:
        self.status = status
        self.title = title
        self.detail = detail
        self.type_ = type_
        super().__init__(detail)


def _problem(request: Request, *, status: int, title: str, detail: str, type_: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type=CONTENT_TYPE,
        content={
            "type": type_,
            "title": title,
            "status": status,
            "detail": detail,
            "instance": str(request.url.path),
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _handle_problem(request: Request, exc: ProblemError) -> JSONResponse:
        return _problem(
            request, status=exc.status, title=exc.title, detail=exc.detail, type_=exc.type_
        )

    @app.exception_handler(InvalidTransition)
    async def _handle_transition(request: Request, exc: InvalidTransition) -> JSONResponse:
        return _problem(
            request,
            status=409,
            title="Invalid status transition",
            detail=str(exc),
            type_=f"{PROBLEM_BASE}/invalid-transition",
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(
            request,
            status=422,
            title="Request validation failed",
            detail="; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()),
            type_=f"{PROBLEM_BASE}/validation-error",
        )
