"""Error shape: {"error": {"code", "message", "detail"?}}."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: Any = None):
        super().__init__(message)
        self.status, self.code, self.message, self.detail = status, code, message, detail


def error_body(code: str, message: str, detail: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if detail is not None:
        err["detail"] = detail
    return {"error": err}


def not_found(what: str = "Not found") -> ApiError:
    return ApiError(404, "not_found", what)


def ai_not_configured() -> ApiError:
    return ApiError(503, "ai_not_configured",
                    "Claude is not set up. Add ANTHROPIC_API_KEY=sk-ant-... to the .env file in the "
                    "project folder and restart the app.")


def _loc_to_field(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(parts) or "body"


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(error_body(exc.code, exc.message, exc.detail), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        detail: dict[str, str] = {}
        for e in exc.errors():
            detail.setdefault(_loc_to_field(tuple(e.get("loc") or ())), e.get("msg") or "invalid")
        return JSONResponse(error_body("validation", "Some fields are invalid.", detail), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)
