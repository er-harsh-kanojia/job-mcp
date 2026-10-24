"""Health, platforms, tasks, search, apply, applications and stats."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field
from sse_starlette import EventSourceResponse

from tools import apply as apply_mod
from tools import search as search_mod
from tools import session as session_mod
from tools import tracker
from tools.ai import providers
from tools.browser import has_session, mark_logged_in, session_info
from tools.config import ROOT_DIR, get_excluded_companies, get_experience_years
from tools.platforms import PLANNED_PLATFORMS, SUPPORTED_PLATFORMS

from . import VERSION, browser_thread
from .errors import ApiError, not_found
from .tasks import Task, manager, sse_format
from .util import public_application, public_job, to_local

log = logging.getLogger("job_mcp.api")
router = APIRouter(prefix="/api")

PLATFORM_NAMES = {"naukri": "Naukri", "instahyre": "Instahyre", "indeed": "Indeed",
                  "linkedin": "LinkedIn", "wellfound": "Wellfound", "hirist": "Hirist"}
_last_checked: dict[str, str] = {}
_mcp_tool_count: int | None = None


def _now_local() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


# ------------------------------------------------------------------ health

async def mcp_tool_count() -> int:
    """Number of tools server.py registers (imported lazily, counted once)."""
    global _mcp_tool_count
    if _mcp_tool_count is None:
        try:
            import server  # noqa: WPS433 (project root is on sys.path)
            _mcp_tool_count = len(await server.mcp.list_tools())
        except Exception as exc:  # pragma: no cover - fallback: count decorators
            log.debug("could not import server.py: %s", exc)
            src = (ROOT_DIR / "server.py").read_text(encoding="utf-8")
            _mcp_tool_count = len(re.findall(r"^@mcp\.tool\(", src, re.M))
    return _mcp_tool_count


@router.get("/health")
async def health():
    p = providers.selected()
    configured = p.is_configured()
    return {"ok": True, "version": VERSION, "mcp_tools": await mcp_tool_count(),
            "ai": {"configured": configured, "provider": p.id, "provider_name": p.name,
                   "model": p.model() if configured else None}}


@router.get("/diagnostics/browser")
async def browser_diagnostics():
    """Launch headless Chromium to about:blank from inside the API process."""
    return await browser_thread.launch_check()


# ---------------------------------------------------------------- platforms

def platform_obj(pid: str) -> dict:
    live = pid in SUPPORTED_PLATFORMS
    info = session_info(pid) if live else {}
    if not live:
        session = "not_set_up"
    elif info.get("logged_in_recorded"):
        session = "logged_in"
    elif info.get("profile_exists"):
        session = "expired"
    else:
        session = "not_set_up"
    last = _last_checked.get(pid) or to_local(info.get("logged_in_at"))
    return {"id": pid, "name": PLATFORM_NAMES.get(pid, pid.title()), "live": live,
            "session": session, "last_checked": last}


def _live_platform(pid: str) -> str:
    pid = (pid or "").lower()
    if pid in PLANNED_PLATFORMS:
        raise ApiError(400, "platform_not_live", f"{PLATFORM_NAMES.get(pid, pid)} is planned but not supported yet.")
    if pid not in SUPPORTED_PLATFORMS:
        raise not_found(f"Unknown platform '{pid}'.")
    return pid


@router.get("/platforms")
async def platforms():
    return {"platforms": [platform_obj(p) for p in [*SUPPORTED_PLATFORMS, *PLANNED_PLATFORMS]]}


@router.post("/platforms/{pid}/check")
async def check_platform(pid: str):
    pid = _live_platform(pid)
    res = await browser_thread.run(lambda: session_mod.check_login(pid, headless=True))
    _last_checked[pid] = _now_local()
    if res.get("logged_in") and not has_session(pid):
        mark_logged_in(pid)
    obj = platform_obj(pid)
    if res.get("error"):
        obj["session"] = "unknown"
        obj["error"] = res["error"]
    return obj


class LoginBody(BaseModel):
    timeout_seconds: int = Field(300, ge=30, le=1800)


@router.post("/platforms/{pid}/login")
async def login_platform(pid: str, body: LoginBody | None = None):
    pid = _live_platform(pid)
    timeout = (body or LoginBody()).timeout_seconds

    async def run(task: Task):
        task.emit("status", {"state": "waiting_for_user"})
        res = await browser_thread.run(lambda: session_mod.interactive_login(pid, timeout_seconds=timeout))
        status = res.get("status")
        if status == "error":
            raise ApiError(500, "login_failed", res.get("message") or "Login failed.")
        task.emit("status", {"state": "logged_in" if status == "logged_in" else "timeout",
                             "message": res.get("message")})
        _last_checked[pid] = _now_local()
        return {"platform": pid, "status": status, "platform_info": platform_obj(pid)}

    return {"task_id": manager.start("login", run).id}


# -------------------------------------------------------------------- tasks

@router.get("/tasks")
async def list_tasks(kind: str | None = None, status: str | None = None):
    """Tasks kept in memory, newest first, e.g. ?kind=apply&status=running to find a run to re-attach to."""
    return {"tasks": [t.snapshot() for t in manager.list(kind, status)]}


@router.get("/tasks/{task_id}")
async def task_snapshot(task_id: str):
    task = manager.get(task_id)
    if task is None:
        raise not_found("Unknown task.")
    return task.snapshot()


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request, last_event_id: str | None = Header(None)):
    task = manager.get(task_id)
    if task is None:
        raise not_found("Unknown task.")
    try:
        last = int(last_event_id) if last_event_id not in (None, "") else None
    except ValueError:
        last = None

    async def gen():
        async for eid, event, data in task.stream(last):
            yield sse_format(eid, event, data)

    return EventSourceResponse(gen(), ping=15)


@router.post("/tasks/{task_id}/cancel")
async def task_cancel(task_id: str):
    task = manager.cancel(task_id)
    if task is None:
        raise not_found("Unknown task.")
    return task.snapshot()


# ------------------------------------------------------------------- search

class SearchBody(BaseModel):
    keywords: list[str] = Field(min_length=1)
    location: str = "India"
    experience_years: int | None = Field(None, ge=0, le=50)
    platforms: list[str] | None = None
    min_match_score: float = Field(0.25, ge=0, le=1)
    limit_per_platform: int | None = Field(None, ge=1, le=200)
    max_jobs: int | None = Field(50, ge=1, le=1000)
    exclude_companies: list[str] | None = None


@router.post("/search")
async def start_search(body: SearchBody):
    keywords = [k.strip() for k in body.keywords if k and k.strip()]
    if not keywords:
        raise ApiError(422, "validation", "Some fields are invalid.", {"keywords": "Enter at least one keyword."})
    wanted = [p.lower() for p in (body.platforms or SUPPORTED_PLATFORMS)]
    bad = [p for p in wanted if p not in SUPPORTED_PLATFORMS and p not in PLANNED_PLATFORMS]
    if bad:
        raise ApiError(422, "validation", "Some fields are invalid.",
                       {"platforms": f"Unknown platform(s): {', '.join(bad)}"})
    exp = body.experience_years if body.experience_years is not None else get_experience_years()
    exclude_comps = [c.strip() for c in body.exclude_companies if c and c.strip()] if body.exclude_companies is not None else get_excluded_companies()
    params = {"keywords": keywords, "location": body.location, "experience_years": exp,
              "platforms": wanted, "min_match_score": body.min_match_score, "max_jobs": body.max_jobs,
              "exclude_companies": exclude_comps}

    async def run(task: Task):
        state: dict[str, dict] = {}       # platform -> aggregated status
        all_jobs: list[dict] = []
        seen: set[str] = set()

        def on_platform(ev: dict, kw_index: int) -> None:
            p = ev["platform"]
            st = state.setdefault(p, {"platform": p, "state": "queued", "count": 0, "ok": 0, "fail": None,
                                      "partial_reason": None})
            last_kw = kw_index == len(keywords) - 1
            s = ev["state"]
            if s == "queued":
                if kw_index == 0:
                    task.emit("platform", {"platform": p, "state": "queued"})
                return
            if s == "skipped":
                st.update(state="skipped", message=ev.get("message"))
                if kw_index == 0:
                    out = {"platform": p, "state": "skipped", "count": 0}
                    if ev.get("message"):
                        out["message"] = ev["message"]
                    task.emit("platform", out)
                return
            if s == "fetching":
                if st["state"] != "fetching":
                    st["state"] = "fetching"
                    task.emit("platform", {"platform": p, "state": "fetching", "count": st["count"]})
                return
            new = []
            for j in ev.get("jobs") or []:
                if j["apply_url"] not in seen:
                    seen.add(j["apply_url"])
                    new.append(j)
            st["count"] += len(new)
            if s == "done":
                st["ok"] += 1
                if ev.get("reason"):
                    st["partial_reason"] = (ev["reason"], ev.get("message"))
            else:
                st["fail"] = (ev.get("reason") or "error", ev.get("message"))
            if new:
                task.emit("jobs", {"platform": p, "jobs": [public_job(j) for j in new]})
            if last_kw:
                if st["ok"]:
                    out = {"platform": p, "state": "done", "count": st["count"]}
                    extra = st["partial_reason"] or st["fail"]
                    if extra:
                        out["reason"], out["message"] = extra[0], extra[1]
                else:
                    reason, msg = st["fail"] or ("error", None)
                    out = {"platform": p, "state": "failed", "count": st["count"], "reason": reason}
                    if msg:
                        out["message"] = msg
                st["final"] = out
                task.emit("platform", out)
            elif st["state"] != "fetching":
                st["state"] = "fetching"

        all_urls: set[str] = set()

        async def work():
            for i, kw in enumerate(keywords):
                jobs = await search_mod.search_jobs(
                    keywords=[kw], location=body.location, experience_years=exp, platforms=wanted,
                    limit_per_platform=body.limit_per_platform,
                    on_platform=lambda ev, i=i: on_platform(ev, i))
                for j in jobs:
                    if j["apply_url"] not in all_urls:
                        all_urls.add(j["apply_url"])
                        all_jobs.append(j)
            return all_jobs

        await browser_thread.run(work)
        await asyncio.sleep(0)  # let thread-safe emits land before the final event
        all_jobs.sort(key=lambda j: float(j.get("rank_score") or 0), reverse=True)
        if body.max_jobs is not None:
            all_jobs = all_jobs[:body.max_jobs]
        filtered = search_mod.filter_jobs(all_jobs, min_match_score=body.min_match_score, experience_years=exp,
                                          exclude_companies=exclude_comps)
        finals = [st.get("final") or {"platform": p, "state": st["state"], "count": st["count"]}
                  for p, st in state.items()]
        tracker.save_search_run(params, finals, filtered, all_jobs)
        return {"total": len(all_jobs), "shown": len(filtered), "jobs": [public_job(j) for j in filtered]}

    return {"task_id": manager.start("search", run).id}


@router.get("/search/last")
async def last_search():
    last = tracker.last_search()
    if last is None:
        return None
    return {"params": last["params"], "finished_at": to_local(last["finished_at"]),
            "platforms": last["platforms"], "total": last["total"],
            "jobs": [public_job(j) for j in last["jobs"]]}


# -------------------------------------------------------------------- apply

class ApplyBody(BaseModel):
    apply_urls: list[str] = Field(min_length=1)
    max_applications: int = Field(10, ge=1, le=1000)
    dry_run: bool = True
    confirm: str | None = None


class PreviewBody(BaseModel):
    apply_urls: list[str] = Field(min_length=1)
    max_applications: int = Field(10, ge=1, le=1000)


def _lookup(urls: list[str]) -> tuple[list[dict], list[str]]:
    found = tracker.get_cached_jobs(urls)
    jobs, missing = [], []
    for u in dict.fromkeys(urls):
        (jobs.append(found[u]) if u in found else missing.append(u))
    return jobs, missing


@router.post("/apply/preview")
async def apply_preview(body: PreviewBody):
    jobs, missing = _lookup(body.apply_urls)
    will_apply, will_skip = [], []
    ex_comps = get_excluded_companies()
    for j in jobs:
        pj = public_job(j)
        platform = (j.get("platform") or "").lower()
        if pj["already_applied"]:
            will_skip.append({"job": pj, "reason": "already_applied"})
        elif not j.get("easy_apply"):
            will_skip.append({"job": pj, "reason": "not_easy_apply"})
        elif search_mod.is_company_excluded(j.get("company"), ex_comps):
            will_skip.append({"job": pj, "reason": "excluded_company"})
        elif platform in SUPPORTED_PLATFORMS and not has_session(platform):
            will_skip.append({"job": pj, "reason": "session_expired"})
        elif len(will_apply) >= body.max_applications:
            will_skip.append({"job": pj, "reason": "over_limit"})
        else:
            will_apply.append(pj)
    return {"will_apply": will_apply, "will_skip": will_skip, "not_found": missing}


@router.post("/apply")
async def start_apply(body: ApplyBody):
    if not body.dry_run and body.confirm != "APPLY":
        raise ApiError(400, "confirm_required",
                       'Live applications need explicit confirmation: send confirm: "APPLY".')
    jobs, missing = _lookup(body.apply_urls)
    if not jobs:
        raise ApiError(400, "jobs_not_found", "None of these jobs are in the search cache. Search again first.",
                       {"missing": missing})

    async def run(task: Task):
        finished: set[str] = set()
        known: set[str] = set()
        terminal = {"applied", "dry_run", "failed", "skipped"}

        def on_job(ev: dict) -> None:
            url = ev.get("apply_url") or ""
            known.add(url)
            task.emit("job", ev)
            if ev["state"] in terminal:
                finished.add(url)
            task.emit("progress", {"done": len(finished), "total": len(known)})

        for u in missing:
            on_job({"apply_url": u, "title": "", "company": "", "platform": "", "state": "skipped",
                    "error": "not in the last search results"})
        result = await browser_thread.run(lambda: apply_mod.bulk_apply(
            jobs, max_applications=body.max_applications, dry_run=body.dry_run,
            on_job=on_job, cancel_event=task.cancel_event))
        await asyncio.sleep(0)
        return result

    task = manager.start("apply", run)
    task.meta = {"dry_run": body.dry_run, "requested": len(body.apply_urls)}
    return {"task_id": task.id}


# ------------------------------------------------------------- applications

def _csv(v: str | None) -> list[str]:
    return [x.strip().lower() for x in (v or "").split(",") if x.strip()]


@router.get("/applications")
async def applications(days: int = Query(0, ge=0), status: str | None = None, platform: str | None = None):
    rows = tracker.list_applications(days=days or None, statuses=_csv(status), platforms=_csv(platform))
    return {"applications": [public_application(r) for r in rows]}


@router.get("/stats")
async def stats():
    s = tracker.stats()
    s["recent"] = [public_application(r) for r in s["recent"]]
    return s
