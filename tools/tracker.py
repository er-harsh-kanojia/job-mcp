"""SQLite application tracker (data/applications.db)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .config import ROOT_DIR
from .normalize import canonical_url

STATUSES = ("applied", "failed", "skipped", "dry_run")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT NOT NULL,
    job_id      TEXT,
    title       TEXT,
    company     TEXT,
    location    TEXT,
    apply_url   TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL CHECK (status IN ('applied','failed','skipped','dry_run')),
    error       TEXT,
    applied_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_applications_applied_at ON applications(applied_at);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);

-- Every job seen by a search (latest copy wins), for apply-by-URL and the
-- resume demand analysis. job_json is the full normalised + scored job.
CREATE TABLE IF NOT EXISTS jobs_cache (
    apply_url   TEXT PRIMARY KEY,
    platform    TEXT,
    title       TEXT,
    job_json    TEXT NOT NULL,
    params_json TEXT,
    cached_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_cache_cached_at ON jobs_cache(cached_at);

-- Finished searches (the web UI's "last search").
CREATE TABLE IF NOT EXISTS search_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    params_json    TEXT NOT NULL,
    platforms_json TEXT NOT NULL,
    urls_json      TEXT NOT NULL,
    total          INTEGER NOT NULL DEFAULT 0,
    finished_at    TEXT NOT NULL
);
"""

_lock = threading.Lock()


def db_path() -> Path:
    """DB location (override with JOB_MCP_DB, e.g. for tests)."""
    return Path(os.environ.get("JOB_MCP_DB") or (ROOT_DIR / "data" / "applications.db"))


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        conn = sqlite3.connect(str(path), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript(_SCHEMA)
            yield conn
            conn.commit()
        finally:
            conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _key(url: str) -> str:
    return canonical_url(url) or (url or "").strip()


def has_applied(apply_url: str) -> bool:
    """True if this URL was applied to (or the site said it already was)."""
    if not apply_url:
        return False
    with _connect() as conn:
        row = conn.execute(
            "SELECT status, error FROM applications WHERE apply_url = ?", (_key(apply_url),)).fetchone()
    if row is None:
        return False
    if row["status"] == "applied":
        return True
    return row["status"] == "skipped" and (row["error"] or "").lower().startswith("already applied")


def record(job: dict | None = None, status: str = "applied", error: str | None = None, *,
           platform: str | None = None, job_id: str | None = None, title: str | None = None,
           company: str | None = None, location: str | None = None,
           apply_url: str | None = None) -> None:
    """Insert or update the outcome for a job (keyed by apply_url).

    A row already marked 'applied' is never downgraded to another status.
    """
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    job = job or {}
    vals = {
        "platform": platform or job.get("platform") or "",
        "job_id": str(job_id or job.get("job_id") or ""),
        "title": title or job.get("title") or "",
        "company": company or job.get("company") or "",
        "location": location or job.get("location") or "",
        "apply_url": _key(apply_url or job.get("apply_url") or ""),
        "status": status,
        "error": (error or "")[:1000] or None,
        "applied_at": _now(),
    }
    if not vals["apply_url"]:
        raise ValueError("apply_url is required")
    with _connect() as conn:
        conn.execute(
            """INSERT INTO applications (platform, job_id, title, company, location, apply_url,
                                         status, error, applied_at)
               VALUES (:platform, :job_id, :title, :company, :location, :apply_url,
                       :status, :error, :applied_at)
               ON CONFLICT(apply_url) DO UPDATE SET
                   platform=excluded.platform, job_id=excluded.job_id, title=excluded.title,
                   company=excluded.company, location=excluded.location,
                   status=excluded.status, error=excluded.error, applied_at=excluded.applied_at
               WHERE applications.status != 'applied'""",
            vals)


def list_applications(days: int | None = None, status: str | None = None, *,
                      statuses: list[str] | None = None, platform: str | None = None,
                      platforms: list[str] | None = None, limit: int | None = None) -> list[dict]:
    """Tracked applications, newest first. ``days=None`` (or 0 via the API) = all time."""
    q, args = "SELECT * FROM applications WHERE 1=1", []
    if days is not None:
        q += " AND applied_at >= ?"
        args.append(_since(days))
    wanted_status = [x for x in ([status] if status else []) + list(statuses or []) if x]
    if wanted_status:
        q += f" AND status IN ({','.join('?' * len(wanted_status))})"
        args.extend(wanted_status)
    wanted_platform = [x.lower() for x in ([platform] if platform else []) + list(platforms or []) if x]
    if wanted_platform:
        q += f" AND platform IN ({','.join('?' * len(wanted_platform))})"
        args.extend(wanted_platform)
    q += " ORDER BY applied_at DESC, id DESC"
    if limit:
        q += " LIMIT ?"
        args.append(int(limit))
    with _connect() as conn:
        return [dict(r) for r in conn.execute(q, args).fetchall()]


def _since(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()


def _local_midnight_utc() -> str:
    """Start of today (local time), as a UTC ISO string comparable with applied_at."""
    now = datetime.now().astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def stats(window_days: int = 30, recent: int = 10) -> dict:
    """Dashboard numbers.

    applied_today (local day), applied_week (7 days), success_rate =
    applied / (applied + failed) over ``window_days``, by_platform status counts
    over ``window_days``, and the ``recent`` latest rows (any status).
    """
    with _connect() as conn:
        today = conn.execute("SELECT COUNT(*) FROM applications WHERE status='applied' AND applied_at >= ?",
                             (_local_midnight_utc(),)).fetchone()[0]
        week = conn.execute("SELECT COUNT(*) FROM applications WHERE status='applied' AND applied_at >= ?",
                            (_since(7),)).fetchone()[0]
        rows = conn.execute("SELECT platform, status, COUNT(*) AS n FROM applications "
                            "WHERE applied_at >= ? GROUP BY platform, status",
                            (_since(window_days),)).fetchall()
        latest = [dict(r) for r in conn.execute(
            "SELECT * FROM applications ORDER BY applied_at DESC, id DESC LIMIT ?", (recent,)).fetchall()]
    by_platform: dict[str, dict[str, int]] = {}
    ok = bad = 0
    for r in rows:
        bp = by_platform.setdefault(r["platform"] or "unknown", {s: 0 for s in STATUSES})
        bp[r["status"]] = bp.get(r["status"], 0) + r["n"]
        if r["status"] == "applied":
            ok += r["n"]
        elif r["status"] == "failed":
            bad += r["n"]
    return {
        "applied_today": today,
        "applied_week": week,
        "success_rate": round(ok / (ok + bad), 4) if (ok + bad) else 0.0,
        "window_days": window_days,
        "by_platform": by_platform,
        "recent": latest,
    }


# ------------------------------------------------------------- jobs cache

def cache_jobs(jobs: list[dict], params: dict | None = None) -> int:
    """Upsert jobs into jobs_cache (keyed by canonical apply_url). Returns the count."""
    now = _now()
    params_json = json.dumps(params or {}, sort_keys=True, default=str)
    rows = []
    for j in jobs or []:
        url = _key(j.get("apply_url") or "")
        if not url:
            continue
        rows.append((url, j.get("platform") or "", j.get("title") or "",
                     json.dumps(j, default=str), params_json, now))
    if not rows:
        return 0
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO jobs_cache (apply_url, platform, title, job_json, params_json, cached_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(apply_url) DO UPDATE SET platform=excluded.platform,
                   title=excluded.title, job_json=excluded.job_json,
                   params_json=excluded.params_json, cached_at=excluded.cached_at""", rows)
    return len(rows)


def get_cached_jobs(apply_urls: list[str]) -> dict[str, dict]:
    """{requested apply_url: job} for the URLs found in the cache."""
    out: dict[str, dict] = {}
    if not apply_urls:
        return out
    keyed = {u: _key(u) for u in apply_urls if u}
    with _connect() as conn:
        for orig, key in keyed.items():
            row = conn.execute("SELECT job_json FROM jobs_cache WHERE apply_url = ?", (key,)).fetchone()
            if row is not None:
                try:
                    out[orig] = json.loads(row["job_json"])
                except json.JSONDecodeError:
                    continue
    return out


def cached_jobs(days: int | None = 60, limit: int = 2000) -> list[dict]:
    """All cached jobs (newest first), optionally only those cached in the last ``days``."""
    q, args = "SELECT job_json FROM jobs_cache", []
    if days:
        q += " WHERE cached_at >= ?"
        args.append(_since(days))
    q += " ORDER BY cached_at DESC LIMIT ?"
    args.append(int(limit))
    out = []
    with _connect() as conn:
        for row in conn.execute(q, args).fetchall():
            try:
                out.append(json.loads(row["job_json"]))
            except json.JSONDecodeError:
                continue
    return out


def save_search_run(params: dict, platforms: list[dict], shown_jobs: list[dict],
                    all_jobs: list[dict] | None = None) -> str:
    """Cache the jobs and record a finished search. Returns finished_at."""
    cache_jobs(list(all_jobs or []) + list(shown_jobs or []), params)
    finished_at = _now()
    urls = [_key(j.get("apply_url") or "") for j in shown_jobs or [] if j.get("apply_url")]
    with _connect() as conn:
        conn.execute("INSERT INTO search_runs (params_json, platforms_json, urls_json, total, finished_at) "
                     "VALUES (?, ?, ?, ?, ?)",
                     (json.dumps(params or {}, default=str), json.dumps(platforms or [], default=str),
                      json.dumps(urls), len(all_jobs or shown_jobs or []), finished_at))
        # keep the table small
        conn.execute("DELETE FROM search_runs WHERE id NOT IN "
                     "(SELECT id FROM search_runs ORDER BY id DESC LIMIT 20)")
    return finished_at


def last_search() -> dict | None:
    """{"params", "finished_at", "platforms", "total", "jobs"} of the latest search, or None."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM search_runs ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    urls = json.loads(row["urls_json"] or "[]")
    found = get_cached_jobs(urls)
    return {
        "params": json.loads(row["params_json"] or "{}"),
        "finished_at": row["finished_at"],
        "platforms": json.loads(row["platforms_json"] or "[]"),
        "total": row["total"],
        "jobs": [found[u] for u in urls if u in found],
    }


def get_application_summary(days: int = 7) -> dict:
    """{"total", "by_status": {status: n}, "by_platform": {platform: {status: [..]}}}"""
    rows = list_applications(days=days)
    by_status: dict[str, int] = {}
    by_platform: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_platform.setdefault(r["platform"], {}).setdefault(r["status"], []).append({
            "job_title": r["title"],
            "company": r["company"],
            "location": r["location"],
            "job_id": r["job_id"],
            "apply_url": r["apply_url"],
            "applied_at": r["applied_at"],
            "error": r["error"],
        })
    return {"total": len(rows), "days": days, "by_status": by_status, "by_platform": by_platform}
