"""Autopilot: settings, status, run now, and the background scheduler.

A run is an ordinary "apply" task (meta.autopilot = True), so the UI's running bar,
Stop and re-attach-after-reload work for it too. While it searches, it emits
``status`` events ({phase, message}); while it applies, the same ``job`` /
``progress`` events as a manual bulk apply.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from tools import apply as apply_mod
from tools import autopilot, tracker
from tools import search as search_mod
from tools.config import get_experience_years

from . import browser_thread
from .errors import ApiError
from .tasks import Task, manager

log = logging.getLogger("job_mcp.api.autopilot")
router = APIRouter(prefix="/api")

TICK_SECONDS = 30


def _running_apply() -> Task | None:
    running = manager.list("apply", "running")
    return running[0] if running else None


def start(slot: str) -> Task:
    """Start an autopilot run now (``slot`` is the scheduled time, or "manual")."""
    cfg = autopilot.get_config()
    live = bool(cfg["live"])

    async def body(task: Task) -> dict:
        run_id = autopilot.start_run(slot, live, task.id)
        counts: dict[str, Any] = {"searched": 0, "selected": 0, "applied": 0, "failed": 0, "skipped": 0}
        try:
            keywords = [k for k in cfg["keywords"] if k.strip()]
            exp = get_experience_years()
            all_jobs: list[dict] = []
            seen: set[str] = set()

            async def search_all() -> None:
                for i, kw in enumerate(keywords, 1):
                    if task.cancelled:
                        return
                    task.emit("status", {"phase": "searching",
                                         "message": f"Searching \"{kw}\" ({i} of {len(keywords)})"})
                    jobs = await search_mod.search_jobs(keywords=[kw], location=cfg["location"],
                                                        experience_years=exp, platforms=cfg["platforms"])
                    for j in jobs:
                        if j["apply_url"] not in seen:
                            seen.add(j["apply_url"])
                            all_jobs.append(j)

            await browser_thread.run(search_all)
            await asyncio.sleep(0)
            counts["searched"] = len(all_jobs)
            tracker.cache_jobs(all_jobs, {"autopilot": True, "keywords": keywords})
            if task.cancelled:
                autopilot.finish_run(run_id, "cancelled", **counts)
                return {"summary": {"cancelled": True, **counts}, "applied": [], "failed": [], "skipped": []}

            done = autopilot.done_today(live)
            picked = autopilot.select_jobs(all_jobs, cfg, done)
            counts["selected"] = len(picked)
            task.emit("status", {"phase": "applying",
                                 "message": f"Applying to {len(picked)} of {len(all_jobs)} jobs found"})
            if not picked:
                autopilot.finish_run(run_id, "done", message="No new matches within today's limits.", **counts)
                return {"summary": {"dry_run": not live, **counts}, "applied": [], "failed": [], "skipped": []}

            finished: set[str] = set()
            terminal = {"applied", "dry_run", "failed", "skipped"}
            known = {j["apply_url"] for j in picked}

            def on_job(ev: dict) -> None:
                task.emit("job", ev)
                if ev["state"] in terminal:
                    finished.add(ev.get("apply_url") or "")
                task.emit("progress", {"done": len(finished), "total": len(known)})

            result = await browser_thread.run(lambda: apply_mod.bulk_apply(
                picked, max_applications=len(picked), dry_run=not live, on_job=on_job,
                cancel_event=task.cancel_event, human_wait=None if cfg.get("wait_for_me") else 0))
            await asyncio.sleep(0)
            s = result.get("summary") or {}
            counts.update(applied=int(s.get("applied", 0)) + int(s.get("would_apply", 0)),
                          failed=int(s.get("failed", 0)), skipped=int(s.get("skipped", 0)))
            autopilot.finish_run(run_id, "cancelled" if s.get("cancelled") else "done", **counts)
            return result
        except asyncio.CancelledError:
            autopilot.finish_run(run_id, "cancelled", **counts)
            raise
        except Exception as exc:
            autopilot.finish_run(run_id, "error", message=f"{type(exc).__name__}: {exc}"[:300], **counts)
            raise

    task = manager.start("apply", body)
    task.meta = {"dry_run": not live, "autopilot": True, "slot": slot}
    return task


async def tick() -> Task | None:
    """Start the due slot, if any (and nothing else is applying)."""
    cfg = autopilot.get_config()
    if not cfg.get("enabled") or _running_apply() is not None:
        return None
    slot = autopilot.due_slot(cfg)
    if slot is None:
        return None
    log.info("autopilot: starting the %s run (%s)", slot, "live" if cfg["live"] else "dry run")
    return start(slot)


async def scheduler_loop() -> None:
    autopilot.mark_interrupted()
    while True:
        try:
            await tick()
        except Exception:
            log.exception("autopilot: scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)


# ------------------------------------------------------------------ routes

def _status() -> dict:
    cfg = autopilot.get_config()
    running = _running_apply()
    return {
        "config": cfg,
        "next_run_at": autopilot.next_run_at(cfg),
        "running_task_id": running.id if running is not None and running.meta.get("autopilot") else None,
        "today": autopilot.done_today(bool(cfg["live"])),
        "runs": autopilot.recent_runs(10),
    }


class AutopilotBody(BaseModel):
    enabled: bool | None = None
    live: bool | None = None
    times: list[str] | None = None
    platforms: list[str] | None = None
    keywords: list[str] | None = None
    location: str | None = Field(None, max_length=80)
    min_score: float | None = None
    daily_caps: dict[str, int] | None = None
    wait_for_me: bool | None = None
    # Turning on live mode needs the same explicit confirmation as a live bulk apply.
    confirm: str | None = None


@router.get("/autopilot")
async def get_autopilot():
    return _status()


@router.put("/autopilot")
async def put_autopilot(body: AutopilotBody):
    current = autopilot.get_config()
    changes = body.model_dump(exclude_none=True, exclude={"confirm"})
    new = {**current, **changes}
    if new.get("live") and not current.get("live") and body.confirm != "APPLY":
        raise ApiError(400, "confirm_required",
                       'Live autopilot submits real applications: send confirm: "APPLY" to turn it on.')
    errs = autopilot.validate(new)
    if errs:
        raise ApiError(422, "validation", "Some settings are invalid.", errs)
    autopilot.save_config(new)
    return _status()


@router.post("/autopilot/run")
async def run_now():
    if _running_apply() is not None:
        raise ApiError(409, "already_running", "A bulk apply is already running. Stop it first.")
    task = start("manual")
    return {"task_id": task.id}
