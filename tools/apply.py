"""Bulk apply across platforms, one browser context per platform."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import random
import time
from collections import OrderedDict
from typing import Any, Callable

from . import tracker
from .browser import new_page, open_context
from .config import get_profile
from .platforms import SUPPORTED_PLATFORMS, get_adapter
from .platforms.base import APPLIED, DRY_RUN, FAILED, SKIPPED
from .search import is_company_excluded

log = logging.getLogger("job_mcp.apply")

# Generous because a job may wait for the person to answer a chatbot question by hand.
PER_JOB_TIMEOUT = float(os.environ.get("JOB_MCP_APPLY_TIMEOUT", "480"))
DELAY_RANGE = (
    float(os.environ.get("JOB_MCP_DELAY_MIN", "6")),
    float(os.environ.get("JOB_MCP_DELAY_MAX", "15")),
)


JobCallback = Callable[[dict], Any]


def _cancelled(cancel_event) -> bool:
    """Works with threading.Event and asyncio.Event (anything with is_set())."""
    try:
        return bool(cancel_event is not None and cancel_event.is_set())
    except Exception:
        return False


async def _sleep_unless_cancelled(seconds: float, cancel_event) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _cancelled(cancel_event):
            return
        await asyncio.sleep(min(0.25, max(0.0, deadline - time.monotonic())))


class JobStopped(Exception):
    """The run was stopped while this job was in progress."""


async def _run_job(coro, cancel_event) -> dict:
    """Run one application, but give up within a second or two when the run is stopped
    (a job may otherwise sit for minutes waiting for a chatbot answer)."""
    job = asyncio.ensure_future(coro)
    deadline = asyncio.get_running_loop().time() + PER_JOB_TIMEOUT
    try:
        while True:
            done, _ = await asyncio.wait({job}, timeout=1.0)
            if done:
                return job.result()
            if _cancelled(cancel_event):
                raise JobStopped()
            if asyncio.get_running_loop().time() > deadline:
                raise asyncio.TimeoutError()
    finally:
        if not job.done():
            job.cancel()
            try:
                await job
            except BaseException:
                pass


def _browser_gone(exc: BaseException) -> bool:
    """True when Playwright reports that the page/context/browser was closed."""
    return type(exc).__name__ == "TargetClosedError" or "has been closed" in str(exc)


def _brief(job: dict, **extra) -> dict:
    out = {k: job.get(k) for k in ("platform", "job_id", "title", "company", "location", "apply_url")}
    out.update(extra)
    return out


async def bulk_apply(jobs: list[dict], max_applications: int = 20, dry_run: bool = True,
                     delay_range: tuple[float, float] | None = None,
                     on_job: JobCallback | None = None, cancel_event=None) -> dict:
    """Apply to up to ``max_applications`` jobs (in the given order).

    * skips jobs already recorded as applied, and non easy-apply jobs
    * groups by platform and reuses one browser context per platform
    * records every outcome in the tracker
    * dry_run=True never clicks a final submit (statuses are recorded as "dry_run")

    ``on_job`` (optional, sync or async) receives ``{"apply_url", "title", "company",
    "platform", "state": queued|applying|applied|dry_run|failed|skipped, "error"?,
    "permanent"?}`` for every state change. ``cancel_event`` (anything with
    ``is_set()``, e.g. threading.Event) stops the run after the current job; the
    remaining jobs are reported as skipped ("cancelled"), are not recorded in the
    tracker, and summary["cancelled"] is True.
    """
    delay_range = delay_range or DELAY_RANGE
    profile = get_profile()
    summary = {"dry_run": bool(dry_run), "requested": int(max_applications), "considered": 0,
               "attempted": 0, "applied": 0, "would_apply": 0, "failed": 0, "skipped": 0,
               "already_applied": 0, "by_platform": {}, "cancelled": False}
    applied, failed, skipped = [], [], []

    async def emit(job: dict, state: str, error: str | None = None, permanent=None) -> None:
        if on_job is None:
            return
        ev = {"apply_url": job.get("apply_url"), "title": job.get("title"),
              "company": job.get("company"), "platform": (job.get("platform") or "").lower(),
              "state": state}
        if error:
            ev["error"] = error
        if permanent is not None:
            ev["permanent"] = bool(permanent)
        try:
            res = on_job(ev)
            if inspect.isawaitable(res):
                await res
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("apply: progress callback failed: %s", exc)

    def bump(platform: str, key: str) -> None:
        summary["by_platform"].setdefault(platform, {}).setdefault(key, 0)
        summary["by_platform"][platform][key] += 1

    # --- pick candidates -------------------------------------------------
    selected: list[dict] = []
    seen_urls: set[str] = set()
    for job in jobs or []:
        if len(selected) >= max(0, int(max_applications)):
            break
        url = job.get("apply_url") or ""
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        summary["considered"] += 1
        platform = (job.get("platform") or "").lower()
        if tracker.has_applied(url):
            summary["already_applied"] += 1
            skipped.append(_brief(job, reason="already applied (tracker)"))
            await emit(job, "skipped", "already applied (tracker)")
            continue
        if platform not in SUPPORTED_PLATFORMS:
            summary["failed"] += 1
            failed.append(_brief(job, error=f"unsupported platform '{platform}'"))
            await emit(job, "failed", f"unsupported platform '{platform}'", permanent=True)
            continue
        if is_company_excluded(job.get("company"), profile.get("excluded_companies") or []):
            summary["skipped"] += 1
            bump(platform, "skipped")
            skipped.append(_brief(job, reason="excluded company"))
            await emit(job, "skipped", f"excluded company ({job.get('company')})")
            continue
        if not job.get("easy_apply", False):
            summary["skipped"] += 1
            bump(platform, "skipped")
            skipped.append(_brief(job, reason="not an easy-apply job"))
            tracker.record(job, "skipped", "not an easy-apply job (external / company site)")
            await emit(job, "skipped", "not an easy-apply job")
            continue
        selected.append(job)
    for job in selected:
        await emit(job, "queued")

    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for job in selected:
        groups.setdefault(job["platform"].lower(), []).append(job)

    # --- apply, platform by platform -------------------------------------
    first_job = True
    finished: set[str] = set()
    for platform, pjobs in groups.items():
        if _cancelled(cancel_event):
            summary["cancelled"] = True
            break
        try:
            async with open_context(platform) as ctx:
                adapter = get_adapter(platform, context=ctx)
                page = await new_page(ctx)
                logged_in = False
                try:
                    logged_in = await adapter.ensure_logged_in(page)
                except Exception as exc:
                    log.warning("apply: %s login check failed: %s", platform, exc)
                if not logged_in:
                    msg = f"Not logged in to {platform}. Run login first (run.py option 1)."
                    for job in pjobs:
                        summary["failed"] += 1
                        bump(platform, "failed")
                        failed.append(_brief(job, error=msg, reason="session_expired"))
                        tracker.record(job, "failed", msg)
                        finished.add(job.get("apply_url"))
                        await emit(job, "failed", msg)
                    continue

                for job in pjobs:
                    if _cancelled(cancel_event):
                        summary["cancelled"] = True
                        break
                    if not first_job:
                        await _sleep_unless_cancelled(random.uniform(*delay_range), cancel_event)
                        if _cancelled(cancel_event):
                            summary["cancelled"] = True
                            break
                    first_job = False
                    await emit(job, "applying")
                    summary["attempted"] += 1
                    try:
                        res = await _run_job(adapter.apply(job, profile, dry_run=dry_run), cancel_event)
                    except JobStopped:
                        res = {"status": SKIPPED, "error": "stopped by you before this application finished"}
                    except asyncio.TimeoutError:
                        res = {"status": FAILED, "error": f"timed out after {int(PER_JOB_TIMEOUT)}s"}
                    except Exception as exc:
                        if _browser_gone(exc):
                            # The window was closed: every remaining job would fail the same way,
                            # so let the platform-level handler fail them all at once.
                            raise
                        res = {"status": FAILED, "error": f"{type(exc).__name__}: {exc}"}

                    status = res.get("status", FAILED)
                    detail = res.get("error") or res.get("message") or ""
                    extra = {k: v for k, v in res.items() if k not in ("status", "error", "message")}
                    if dry_run and status == APPLIED:  # adapters must not do this; be safe
                        log.error("apply: adapter %s reported 'applied' during dry run", platform)
                    if status in (APPLIED, DRY_RUN):
                        key = "applied" if status == APPLIED else "would_apply"
                        summary[key] += 1
                        bump(platform, key)
                        applied.append(_brief(job, status=status, message=detail, **extra))
                    elif status == SKIPPED:
                        summary["skipped"] += 1
                        bump(platform, "skipped")
                        skipped.append(_brief(job, reason=detail, **extra))
                    else:
                        summary["failed"] += 1
                        bump(platform, "failed")
                        failed.append(_brief(job, error=detail or "unknown error", **extra))
                    try:
                        tracker.record(job, status if status in tracker.STATUSES else FAILED, detail)
                    except Exception as exc:
                        log.warning("apply: could not record outcome: %s", exc)
                    finished.add(job.get("apply_url"))
                    ev_state = status if status in (APPLIED, DRY_RUN, SKIPPED) else FAILED
                    ev_error = None
                    if ev_state == FAILED:
                        ev_error = detail or "unknown error"
                    elif ev_state == SKIPPED:
                        ev_error = detail or None
                    await emit(job, ev_state, ev_error, permanent=extra.get("permanent"))
                    log.info("apply: [%s] %s @ %s -> %s %s", platform, job.get("title"),
                             job.get("company"), status, detail[:80])
        except Exception as exc:
            # browser failed to start or was closed: fail the remaining jobs of this platform
            msg = (f"{platform} browser window was closed, so the run stopped" if _browser_gone(exc)
                   else f"{platform} browser error: {type(exc).__name__}: {exc}")
            log.warning("apply: %s", msg)
            done = {a.get("apply_url") for a in applied + failed + skipped}
            for job in pjobs:
                if job.get("apply_url") not in done:
                    summary["failed"] += 1
                    bump(platform, "failed")
                    failed.append(_brief(job, error=msg))
                    tracker.record(job, "failed", msg)
                    finished.add(job.get("apply_url"))
                    await emit(job, "failed", msg)
        if summary["cancelled"]:
            break

    if summary["cancelled"]:
        for job in selected:
            if job.get("apply_url") not in finished:
                summary["skipped"] += 1
                skipped.append(_brief(job, reason="cancelled"))
                await emit(job, "skipped", "cancelled")

    return {"summary": summary, "applied": applied, "failed": failed, "skipped": skipped}
