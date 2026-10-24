"""AI provider settings, resume review / prep, mock interviews."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sse_starlette import EventSourceResponse

from tools.ai import interview, llm, providers, report, store
from tools.ai.extract import ResumeError
from tools.ai.review import load_resume, run_analysis

from . import browser_thread
from .errors import ApiError, error_body, not_found
from .tasks import Task, manager, sse_format

router = APIRouter(prefix="/api")

_STATUS_BY_CODE = {"ai_not_configured": 503, "provider_not_configured": 400, "ai_rate_limited": 429,
                   "ai_invalid_output": 502, "ai_refused": 422}


def _ai_error(exc: llm.AIError) -> ApiError:
    return ApiError(_STATUS_BY_CODE.get(exc.code, 502), exc.code, exc.message)


def _require_ai() -> providers.Provider:
    p = providers.selected()
    if not p.is_configured():
        raise _ai_error(p.not_configured())
    return p


# ---------------------------------------------------------------- settings

class AISettingsBody(BaseModel):
    provider: Literal["anthropic", "openai", "local"]


@router.get("/settings/ai")
async def get_ai_settings():
    return providers.settings()


@router.put("/settings/ai")
async def put_ai_settings(body: AISettingsBody):
    try:
        providers.select(body.provider)
    except llm.AIError as exc:
        raise _ai_error(exc) from exc
    return providers.settings()


# ------------------------------------------------------------------ review

@router.get("/resume/review")
async def get_review(role: str | None = None):
    """Latest stored review for the role (or the latest of any role if omitted)."""
    return store.get_review(role) if role else store.latest_review()


@router.get("/resume/reviews")
async def list_reviews(all: bool = False):
    """Latest review per role, or every stored review (newest first) with ?all=true."""
    return {"reviews": store.list_reviews(all_history=all)}


@router.get("/resume/reviews/{review_id}")
async def get_review_by_id(review_id: int):
    review = store.get_review_by_id(review_id)
    if review is None:
        raise not_found("Report not found.")
    return review


async def _render_pdf(doc: str) -> bytes:
    """Print an HTML document to PDF with headless Chromium on the browser thread."""
    async def render() -> bytes:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(doc, wait_until="load")
                return await page.pdf(format="A4", print_background=True,
                                      margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
            finally:
                await browser.close()
    return await browser_thread.run(render)


_REPORT_TYPES = {"md": "text/markdown; charset=utf-8", "html": "text/html; charset=utf-8", "pdf": "application/pdf"}


@router.get("/resume/reviews/{review_id}/report")
async def download_report(review_id: int, format: Literal["pdf", "md", "html"] = "pdf"):
    """The review as a downloadable report (built from stored data; no AI call)."""
    review = store.get_review_by_id(review_id)
    if review is None:
        raise not_found("Report not found.")
    if format == "md":
        body: bytes = report.to_markdown(review).encode("utf-8")
    elif format == "html":
        body = report.to_html(review).encode("utf-8")
    else:
        try:
            body = await _render_pdf(report.to_html(review))
        except Exception as exc:
            raise ApiError(500, "pdf_failed", f"Couldn't render the PDF ({type(exc).__name__}). "
                           "Download the Markdown version instead.") from exc
    name = report.filename(review, format)
    return Response(body, media_type=_REPORT_TYPES[format],
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


class AnalyseBody(BaseModel):
    target_role: str = Field(min_length=2, max_length=120)
    # Previous report to compare with: omitted = the latest previous report; 0 = don't compare.
    compare_to: int | None = Field(None, ge=0)


@router.post("/resume/analyse")
async def analyse(body: AnalyseBody):
    _require_ai()
    try:
        load_resume()  # fail fast (no task) if the resume is missing / unreadable
    except ResumeError as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    role = body.target_role
    if body.compare_to and store.get_review_by_id(body.compare_to) is None:
        raise not_found("Report not found.")

    async def run(task: Task):
        review = await run_analysis(role, on_step=lambda ev: task.emit("step", ev),
                                    compare_to=body.compare_to)
        return {"review": review}

    return {"task_id": manager.start("analyse", run).id}


class IssueBody(BaseModel):
    status: Literal["open", "fixed", "dismissed"]


class PlanBody(BaseModel):
    done: bool


class QuestionBody(BaseModel):
    practised: bool


@router.patch("/resume/issues/{issue_id}")
async def patch_issue(issue_id: str, body: IssueBody):
    res = store.set_issue_status(issue_id, body.status)
    if res is None:
        raise not_found("Unknown issue.")
    return res


@router.patch("/resume/plan/{item_id}")
async def patch_plan(item_id: str, body: PlanBody):
    item = store.set_plan_done(item_id, body.done)
    if item is None:
        raise not_found("Unknown plan item.")
    return {"plan_item": item}


@router.patch("/resume/questions/{question_id}")
async def patch_question(question_id: str, body: QuestionBody):
    q = store.set_question_practised(question_id, body.practised)
    if q is None:
        raise not_found("Unknown question.")
    return {"question": q}


# --------------------------------------------------------------- interview

class SessionBody(BaseModel):
    question_id: str
    role: str | None = None


class MessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


def _session_error(exc: interview.SessionError) -> ApiError:
    return ApiError(exc.status, exc.code, exc.message)


@router.post("/interview/sessions")
async def create_session(body: SessionBody):
    _require_ai()
    role = body.role
    if not role:
        found = store.get_question(body.question_id)
        if found:
            r = store.get_review_by_id(found[1])
            role = r["target_role"] if r else ""
    try:
        return await interview.start_session(body.question_id, role or "")
    except interview.SessionError as exc:
        raise _session_error(exc) from exc
    except llm.AIError as exc:
        raise _ai_error(exc) from exc


@router.get("/interview/sessions/{session_id}")
async def get_session(session_id: str):
    sess = store.get_session(session_id)
    if sess is None:
        raise not_found("Unknown interview session.")
    return {k: sess[k] for k in ("session_id", "question_id", "messages", "feedback", "role")}


@router.post("/interview/sessions/{session_id}/messages")
async def post_message(session_id: str, body: MessageBody):
    sess = store.get_session(session_id)
    if sess is None:
        raise not_found("Unknown interview session.")
    if sess["feedback"] is not None:
        raise ApiError(409, "interview_finished", "This practice session is finished. Start a new one.")
    _require_ai()

    async def gen():
        n = 0
        try:
            async for event, data in interview.reply(session_id, body.content):
                yield sse_format(n, event, data)
                n += 1
        except interview.SessionError as exc:
            yield sse_format(n, "error", error_body(exc.code, exc.message)["error"])
        except llm.AIError as exc:
            yield sse_format(n, "error", {"code": exc.code, "message": exc.message})

    return EventSourceResponse(gen(), ping=15)
