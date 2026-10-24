"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from tools.ai import llm
from tools.config import ROOT_DIR

from . import VERSION, errors, routes_ai, routes_jobs, routes_profile
from .errors import error_body

log = logging.getLogger("job_mcp.api")

DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

NOT_BUILT_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Job MCP</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem;color:#222}
code{background:#f3f3f3;padding:.1rem .35rem;border-radius:4px}</style></head><body>
<h1>Job MCP API is running</h1>
<p>frontend not built: <code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code></p>
<p>Then reload this page. The API is at <a href="/api/health">/api/health</a> and its docs at
<a href="/docs">/docs</a>.</p></body></html>"""


def web_dist() -> Path:
    return Path(os.environ.get("JOB_MCP_WEB_DIST") or (ROOT_DIR / "web" / "dist"))


def create_app() -> FastAPI:
    llm.load_env()
    # Tasks started from the UI must not block on a captcha; they report
    # captcha_required instead (the login flow still lets you solve it).
    os.environ.setdefault("JOB_MCP_NONINTERACTIVE", "1")

    app = FastAPI(title="Job MCP", version=VERSION)
    app.add_middleware(CORSMiddleware, allow_origins=DEV_ORIGINS, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    errors.install(app)
    app.include_router(routes_jobs.router)
    app.include_router(routes_profile.router)
    app.include_router(routes_ai.router)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   include_in_schema=False)
    async def api_not_found(rest: str):
        from fastapi.responses import JSONResponse
        return JSONResponse(error_body("not_found", f"No API endpoint /api/{rest}"), status_code=404)

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        from fastapi.responses import FileResponse

        dist = web_dist()
        index = dist / "index.html"
        if not index.is_file():
            return HTMLResponse(NOT_BUILT_HTML)
        if path:
            candidate = (dist / path).resolve()
            try:
                candidate.relative_to(dist.resolve())
            except ValueError:
                return FileResponse(index, headers={"Cache-Control": "no-store"})
            if candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-store"})

    return app
