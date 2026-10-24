"""Small shared helpers for the API layer."""

from __future__ import annotations

from datetime import datetime

from tools import tracker

JOB_KEYS = ("platform", "job_id", "title", "company", "location", "salary", "apply_url",
            "description", "skills", "exp_min", "exp_max", "posted_days_ago",
            "match_score", "rank_score", "easy_apply")


def to_local(ts: str | None) -> str | None:
    """ISO string (UTC with offset, or naive local) -> ISO local time with offset."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return ts
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive values are local
    return dt.astimezone().replace(microsecond=0).isoformat()


def public_job(job: dict, applied: bool | None = None) -> dict:
    out = {k: job.get(k) for k in JOB_KEYS}
    out["skills"] = list(out.get("skills") or [])
    out["salary"] = out.get("salary") or "Not disclosed"
    for k in ("exp_min", "exp_max", "posted_days_ago"):
        out[k] = int(out[k]) if isinstance(out.get(k), (int, float)) else -1
    for k in ("match_score", "rank_score"):
        out[k] = round(float(out.get(k) or 0), 4)
    out["easy_apply"] = bool(out.get("easy_apply"))
    out["already_applied"] = tracker.has_applied(job.get("apply_url") or "") if applied is None else applied
    return out


def public_application(row: dict) -> dict:
    return {"id": row.get("id"), "platform": row.get("platform"), "job_id": row.get("job_id") or "",
            "title": row.get("title") or "", "company": row.get("company") or "",
            "location": row.get("location") or "", "apply_url": row.get("apply_url") or "",
            "status": row.get("status"), "error": row.get("error"), "applied_at": to_local(row.get("applied_at"))}
