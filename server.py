#!/usr/bin/env python3
"""Job MCP server (stdio).

Exposes: list_platforms, login_platform, search_jobs, apply_to_jobs, application_status,
review_resume, interview_prep.

Register with Claude Code:
    claude mcp add job-mcp -- D:\\Job-MCP\\.venv\\Scripts\\python.exe D:\\Job-MCP\\server.py

stdout carries the MCP protocol, so this module never prints; logs go to stderr.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Tool calls from an MCP client must not block waiting for someone to solve a
# captcha: fail soft with "captcha_required" instead (login_platform still lets
# the user solve bot checks in its visible window). Set to 0 to allow waiting.
os.environ.setdefault("JOB_MCP_NONINTERACTIVE", "1")

try:  # mcp 1.x (requirements pin)
    from mcp.server.fastmcp import FastMCP
except ImportError:  # mcp 2.x renamed FastMCP -> MCPServer (same API for what we use)
    from mcp.server.mcpserver import MCPServer as FastMCP  # type: ignore

from tools import apply as apply_mod
from tools import search as search_mod
from tools import session as session_mod
from tools import tracker
from tools.ai import llm as ai_llm
from tools.ai import store as ai_store
from tools.ai.extract import ResumeError
from tools.config import get_experience_years
from tools.platforms import PLANNED_PLATFORMS, SUPPORTED_PLATFORMS

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# AI keys (ANTHROPIC_API_KEY / OPENAI_API_KEY) may live in .env next to this file.
ai_llm.load_env()

mcp = FastMCP(
    "job-mcp",
    instructions=(
        "Search and apply to jobs on Naukri, Instahyre and Indeed using the user's saved "
        "browser sessions. Typical flow: list_platforms -> (login_platform if no session) -> "
        "search_jobs -> show the user the results -> apply_to_jobs with dry_run=true -> only "
        "after the user explicitly confirms, apply_to_jobs with dry_run=false. "
        "review_resume / interview_prep return the stored resume review and prep plan for a "
        "target role (or the resume text + profile to review yourself when no AI key is set)."
    ),
)

# Last search results, so apply_to_jobs can be called with just apply_urls.
_last_results: dict[str, dict] = {}

_JOB_KEYS = ("platform", "job_id", "title", "company", "location", "salary", "apply_url",
             "description", "skills", "exp_min", "exp_max", "posted_days_ago",
             "match_score", "rank_score", "easy_apply")


def _public(job: dict, desc_len: int = 300) -> dict:
    out = {k: job.get(k) for k in _JOB_KEYS}
    d = out.get("description") or ""
    out["description"] = d[:desc_len] + ("…" if len(d) > desc_len else "")
    return out


@mcp.tool()
async def list_platforms() -> dict[str, Any]:
    """List supported job platforms and whether a saved login session exists for each."""
    return {
        "supported": list(SUPPORTED_PLATFORMS),
        "planned_not_implemented": list(PLANNED_PLATFORMS),
        "sessions": session_mod.session_status(),
    }


@mcp.tool()
async def login_platform(platform: str, timeout_seconds: int = 300) -> dict[str, Any]:
    """Open a visible browser on the platform's login page so the user can sign in manually.

    The session is saved for later searches/applications. Waits until login is
    detected, the window is closed, or timeout_seconds passes.
    """
    return await session_mod.interactive_login(platform, timeout_seconds=timeout_seconds)


@mcp.tool()
async def search_jobs(keywords: list[str], location: str = "India",
                      experience_years: int | None = None,
                      platforms: list[str] | None = None,
                      min_match_score: float = 0.25,
                      max_results: int = 50,
                      limit_per_platform: int = 40,
                      exclude_companies: list[str] | None = None) -> dict[str, Any]:
    """Search jobs across platforms (default: all supported), score, dedupe and filter them.

    keywords: e.g. ["ML Engineer", "GenAI Engineer"] (each is searched separately).
    experience_years: defaults to the profile value in config.json.
    exclude_companies: optional list of company names to filter out (case-insensitive).
    Returns jobs sorted by rank_score (match + recency).
    """
    exp = experience_years if experience_years is not None else get_experience_years()
    all_jobs: list[dict] = []
    seen: set[str] = set()
    for kw in keywords or []:
        jobs = await search_mod.search_jobs(keywords=[kw], location=location, experience_years=exp,
                                            platforms=platforms, limit_per_platform=limit_per_platform)
        for j in jobs:
            if j["apply_url"] not in seen:
                seen.add(j["apply_url"])
                all_jobs.append(j)
    filtered = search_mod.filter_jobs(all_jobs, min_match_score=min_match_score, experience_years=exp,
                                      exclude_companies=exclude_companies)
    for j in filtered:
        _last_results[j["apply_url"]] = j
    try:  # shared cache: the web UI's apply-by-URL and the resume demand analysis use it
        tracker.cache_jobs(all_jobs, {"keywords": keywords, "location": location, "experience_years": exp,
                                      "platforms": platforms, "source": "mcp"})
    except Exception as exc:
        logging.getLogger("job_mcp.server").warning("could not cache jobs: %s", exc)
    by_platform: dict[str, int] = {}
    for j in filtered:
        by_platform[j["platform"]] = by_platform.get(j["platform"], 0) + 1
    return {
        "total_found": len(all_jobs),
        "after_filter": len(filtered),
        "by_platform": by_platform,
        "jobs": [_public(j) for j in filtered[:max_results]],
    }


@mcp.tool()
async def apply_to_jobs(apply_urls: list[str] | None = None,
                        jobs: list[dict[str, Any]] | None = None,
                        max_applications: int = 10,
                        dry_run: bool = True) -> dict[str, Any]:
    """Apply to jobs. dry_run=True (default) never submits anything.

    Pass apply_urls from a previous search_jobs call (preferred), or full job dicts.
    Only set dry_run=false after the user has explicitly confirmed.
    """
    selected: list[dict] = []
    cached = tracker.get_cached_jobs([u for u in apply_urls or [] if u not in _last_results])
    for url in apply_urls or []:
        if url in _last_results:
            selected.append(_last_results[url])
        elif url in cached:
            selected.append(cached[url])
        else:
            selected.append({"apply_url": url, "title": "", "company": "", "platform": _guess_platform(url),
                             "easy_apply": True})
    for j in jobs or []:
        if isinstance(j, dict) and j.get("apply_url"):
            full = dict(_last_results.get(j["apply_url"], {}))
            full.update(j)
            full.setdefault("platform", _guess_platform(j["apply_url"]))
            selected.append(full)
    if not selected:
        return {"error": "No jobs given. Pass apply_urls from search_jobs results."}
    return await apply_mod.bulk_apply(selected, max_applications=max_applications, dry_run=dry_run)


def _guess_platform(url: str) -> str:
    u = (url or "").lower()
    for p in SUPPORTED_PLATFORMS:
        if p in u:
            return p
    return ""


@mcp.tool()
async def application_status(days: int = 7) -> dict[str, Any]:
    """Summary of tracked applications (applied / failed / skipped / dry_run) in the last N days."""
    return tracker.get_application_summary(days=days)


async def _review_or_run(target_role: str) -> dict[str, Any]:
    """Stored review for the role; runs an analysis if none exists and an AI key is set."""
    from tools.ai import review as review_mod
    review = ai_store.get_review(target_role)
    if review is not None:
        return {"source": "stored", "review": review}
    provider = ai_llm.provider()
    if not provider.is_configured():
        return review_mod.offline_context(target_role)
    try:
        return {"source": "new_analysis", "provider": provider.id,
                "review": await review_mod.run_analysis(target_role)}
    except ResumeError as exc:
        return {"error": exc.code, "message": exc.message}
    except ai_llm.AIError as exc:
        return {"error": exc.code, "message": exc.message}


@mcp.tool()
async def review_resume(target_role: str) -> dict[str, Any]:
    """Resume review for a target role (e.g. "GenAI Engineer").

    Returns the stored review (scores, overall/projected, issues with before/after
    rewrites), running a new analysis with the configured AI provider (Claude or
    ChatGPT) if none exists yet. Without an AI key it returns the extracted resume
    text and profile so you can do the review yourself; never invent experience.
    """
    res = await _review_or_run(target_role)
    review = res.get("review")
    if review is None:
        return res
    keep = ("target_role", "analysed_at", "resume_filename", "model", "provider", "scores", "overall",
            "projected", "issues")
    return {"source": res["source"], "review": {k: review.get(k) for k in keep},
            "resume_lines": {ln["id"]: ln["text"] for s in review.get("sections") or [] for ln in s["lines"]}}


@mcp.tool()
async def interview_prep(target_role: str) -> dict[str, Any]:
    """Interview prep for a target role: skill demand (from cached job searches) vs the
    resume, a two-week plan, and likely interview questions with answer outlines and how
    to use the candidate's own resume evidence. Runs the analysis if needed (AI key
    required); without a key it returns the resume text, profile and demand counts."""
    res = await _review_or_run(target_role)
    review = res.get("review")
    if review is None:
        return res
    return {"source": res["source"], "target_role": review.get("target_role"),
            "analysed_at": review.get("analysed_at"), "provider": review.get("provider"),
            "prep": review.get("prep")}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
