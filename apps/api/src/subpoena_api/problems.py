"""RFC 9457 ``application/problem+json`` errors."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_BASE = "https://api.subpoena.ai/problems/"
MEDIA_TYPE = "application/problem+json"


class ProblemError(Exception):
    def __init__(
        self,
        status: int,
        slug: str,
        detail: str | None = None,
        *,
        title: str | None = None,
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        super().__init__(detail or slug)
        self.status = status
        self.slug = slug
        self.title = title or HTTPStatus(status).phrase
        self.detail = detail
        self.headers = headers
        self.extensions = extensions


def problem_response(
    request: Request,
    status: int,
    slug: str,
    title: str,
    detail: str | None = None,
    headers: dict[str, str] | None = None,
    **extensions: Any,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": PROBLEM_BASE + slug,
        "title": title,
        "status": status,
        "instance": request.url.path,
    }
    if detail:
        body["detail"] = detail
    body.update(extensions)
    return JSONResponse(body, status_code=status, media_type=MEDIA_TYPE, headers=headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(
            request, exc.status, exc.slug, exc.title, exc.detail, exc.headers, **exc.extensions
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem_response(
            request,
            422,
            "validation-error",
            "Request validation failed",
            f"{len(errors)} field(s) failed validation",
            errors=errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        title = HTTPStatus(exc.status_code).phrase
        slug = title.lower().replace(" ", "-")
        detail = exc.detail if isinstance(exc.detail, str) and exc.detail != title else None
        headers = dict(exc.headers) if exc.headers else None
        return problem_response(request, exc.status_code, slug, title, detail, headers)
