"""Aggregated multi-platform job search."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from typing import Any, Callable, Iterable

from .browser import captcha_hint
from .config import get_excluded_companies, get_experience_years, get_preferred_locations, get_skill_experience
from .normalize import dedupe_jobs, normalize_job
from .platforms import SUPPORTED_PLATFORMS, get_adapter
from .scoring import compute_match_score, compute_rank_score, experience_incompatible

log = logging.getLogger("job_mcp.search")

DEFAULT_LIMIT_PER_PLATFORM = int(os.environ.get("JOB_MCP_LIMIT_PER_PLATFORM", "40"))


# Failure reasons reported through ``on_platform`` (see search_jobs).
REASON_CAPTCHA = "captcha_required"
REASON_SESSION = "session_expired"
REASON_TIMEOUT = "timeout"
REASON_ERROR = "error"

PlatformCallback = Callable[[dict], Any]


async def _emit(cb: PlatformCallback | None, event: dict) -> None:
    """Call a sync or async progress callback; never let it break the search."""
    if cb is None:
        return
    try:
        res = cb(event)
        if inspect.isawaitable(res):
            await res
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("search: progress callback failed: %s", exc)


def _classify_exception(exc: BaseException) -> str:
    from .platforms.base import NotLoggedIn
    if isinstance(exc, NotLoggedIn):
        return REASON_SESSION
    text = f"{type(exc).__name__} {exc}".lower()
    if "captcha" in text or "verify you are human" in text:
        return REASON_CAPTCHA
    if "not logged in" in text or "login required" in text or "session expired" in text:
        return REASON_SESSION
    return REASON_ERROR


async def _search_one(platform: str, keywords: list[str], location: str,
                      experience_years: int, limit: int, timeout: float | None,
                      on_platform: PlatformCallback | None = None) -> list[dict]:
    """Run one adapter; never raises (fail soft). Reports its state via ``on_platform``."""
    try:
        adapter = get_adapter(platform)
    except Exception as exc:
        log.warning("search: skipping platform %r: %s", platform, exc)
        await _emit(on_platform, {"platform": platform, "state": "skipped", "count": 0,
                                  "reason": REASON_ERROR, "message": str(exc)})
        return []
    await _emit(on_platform, {"platform": platform, "state": "fetching"})
    t = timeout or adapter.search_timeout
    try:
        raw = await asyncio.wait_for(
            adapter.search(keywords, location, experience_years, limit), timeout=t)
    except asyncio.TimeoutError:
        log.warning("search: %s timed out after %ss", platform, int(t))
        await _emit(on_platform, {"platform": platform, "state": "failed", "count": 0,
                                  "reason": REASON_TIMEOUT,
                                  "message": f"timed out after {int(t)}s"})
        return []
    except Exception as exc:
        log.warning("search: %s failed: %s: %s", platform, type(exc).__name__, exc)
        await _emit(on_platform, {"platform": platform, "state": "failed", "count": 0,
                                  "reason": _classify_exception(exc),
                                  "message": f"{type(exc).__name__}: {exc}"[:300]})
        return []
    jobs = []
    for r in raw or []:
        try:
            j = normalize_job(r, platform)
            if j["apply_url"] and j["title"]:
                jobs.append(j)
        except Exception as exc:
            log.debug("search: bad record from %s: %s", platform, exc)
    log.info("search: %s returned %d jobs", platform, len(jobs))
    issue = getattr(adapter, "search_issue", None)
    event: dict = {"platform": platform, "state": "done", "count": len(jobs), "jobs": jobs}
    if issue:
        # Partial results are still "done"; no results at all is a failure.
        event["reason"] = issue
        event["message"] = (captcha_hint(platform) if issue == REASON_CAPTCHA
                            else f"{platform}: {issue}")
        if not jobs:
            event["state"] = "failed"
    await _emit(on_platform, event)
    return jobs


def score_jobs(jobs: Iterable[dict], keywords: list[str], experience_years: int | None,
               profile_skills: list[str] | None = None,
               preferred_locations: list[str] | None = None) -> list[dict]:
    """Set match_score and rank_score in place; returns the list."""
    if profile_skills is None:
        profile_skills = list(get_skill_experience())
    if preferred_locations is None:
        preferred_locations = get_preferred_locations()
    out = []
    for j in jobs:
        j["match_score"] = compute_match_score(j, keywords, experience_years,
                                               profile_skills, preferred_locations)
        j["rank_score"] = compute_rank_score(j["match_score"], j.get("posted_days_ago", -1))
        out.append(j)
    return out


async def search_jobs(keywords: list[str], location: str = "India",
                      experience_years: int | None = None,
                      platforms: list[str] | None = None,
                      limit_per_platform: int | None = None,
                      timeout: float | None = None,
                      on_platform: PlatformCallback | None = None) -> list[dict]:
    """Search all requested platforms concurrently.

    Returns normalised, scored, de-duplicated jobs sorted by rank_score (desc).
    Platform failures are logged and produce no results; they never raise.

    ``on_platform`` (optional, sync or async) receives one dict per state change:
    ``{"platform", "state": queued|fetching|done|failed|skipped, "count"?,
    "reason"?: captcha_required|session_expired|timeout|error, "message"?,
    "jobs"?}``. The "done" event carries that platform's normalised, scored jobs.
    """
    keywords = [k.strip() for k in (keywords or []) if k and k.strip()]
    if experience_years is None:
        experience_years = get_experience_years()
    wanted = [p.strip().lower() for p in (platforms or SUPPORTED_PLATFORMS) if p and p.strip()]
    unknown = [p for p in wanted if p not in SUPPORTED_PLATFORMS]
    for p in dict.fromkeys(unknown):
        log.warning("search: unsupported platform %r ignored (supported: %s)", p, ", ".join(SUPPORTED_PLATFORMS))
        await _emit(on_platform, {"platform": p, "state": "skipped", "count": 0,
                                  "message": "platform not supported yet"})
    wanted = [p for p in dict.fromkeys(wanted) if p in SUPPORTED_PLATFORMS]
    if not wanted:
        return []
    limit = limit_per_platform or DEFAULT_LIMIT_PER_PLATFORM
    for p in wanted:
        await _emit(on_platform, {"platform": p, "state": "queued"})

    scoring_cb = None
    if on_platform is not None:
        async def scoring_cb(event: dict) -> None:
            # score the per-platform partial results before reporting them
            if event.get("jobs"):
                score_jobs(event["jobs"], keywords, experience_years)
            await _emit(on_platform, event)

    results = await asyncio.gather(
        *(_search_one(p, keywords, location, experience_years, limit, timeout, scoring_cb)
          for p in wanted),
        return_exceptions=True)
    jobs: list[dict] = []
    for p, r in zip(wanted, results):
        if isinstance(r, BaseException):  # defensive: _search_one shouldn't raise
            log.warning("search: %s crashed: %s", p, r)
            await _emit(on_platform, {"platform": p, "state": "failed", "count": 0,
                                      "reason": REASON_ERROR, "message": str(r)[:300]})
            continue
        jobs.extend(r)

    score_jobs(jobs, keywords, experience_years)
    jobs = dedupe_jobs(jobs)
    jobs.sort(key=lambda j: j["rank_score"], reverse=True)
    return jobs


def is_company_excluded(company: str | None, excluded_companies: Iterable[str] | None) -> bool:
    """Check if a company matches any name in excluded_companies (case-insensitive substring/equality)."""
    if not company or not excluded_companies:
        return False
    c = str(company).strip().lower()
    for ex in excluded_companies:
        ex_clean = str(ex).strip().lower()
        if ex_clean and (ex_clean == c or ex_clean in c):
            return True
    return False


def filter_jobs(jobs: list[dict], min_match_score: float = 0.25,
                experience_years: int | None = None,
                exclude_companies: list[str] | None = None) -> list[dict]:
    """Drop low matches, clearly experience-incompatible jobs, and excluded companies; sort by rank_score."""
    if experience_years is None:
        experience_years = get_experience_years()
    if exclude_companies is None:
        exclude_companies = get_excluded_companies()
    kept = [j for j in (jobs or [])
            if float(j.get("match_score") or 0) >= min_match_score
            and not experience_incompatible(j, experience_years)
            and not is_company_excluded(j.get("company"), exclude_companies)]
    kept = dedupe_jobs(kept)
    kept.sort(key=lambda j: (float(j.get("rank_score") or 0), float(j.get("match_score") or 0)),
              reverse=True)
    return kept
