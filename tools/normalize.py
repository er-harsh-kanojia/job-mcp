"""Pure helpers for normalising job records (no I/O, easy to unit test)."""

from __future__ import annotations

import html
import re
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

NOT_DISCLOSED = "Not disclosed"
OPEN_ENDED = 99  # exp_max for "N+ years"

JOB_FIELDS_DEFAULTS: dict[str, Any] = {
    "platform": "",
    "job_id": "",
    "title": "",
    "company": "",
    "location": "",
    "salary": NOT_DISCLOSED,
    "apply_url": "",
    "description": "",
    "skills": [],
    "exp_min": -1,
    "exp_max": -1,
    "posted_days_ago": -1,
    "match_score": 0.0,
    "rank_score": 0.0,
    "easy_apply": False,
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str | None, max_len: int | None = None) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", str(text))
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    if max_len and len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (text or "").lower())
    return text.strip("-")


# ---------------------------------------------------------------- experience

_RANGE_RE = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*(?:-|–|—|to)\s*(\d{1,2}(?:\.\d)?)\s*(?:\+)?\s*(?:yrs?|years?|y\b)?",
    re.I)
_PLUS_RE = re.compile(r"(\d{1,2})\s*\+\s*(?:yrs?|years?)?", re.I)
_MIN_RE = re.compile(r"(?:min(?:imum)?|at\s*least|over|more\s+than)\s*(?:of\s*)?(\d{1,2})\s*(?:\+)?\s*(?:yrs?|years?)", re.I)
_SINGLE_RE = re.compile(r"(\d{1,2})\s*(?:yrs?|years?)\b", re.I)


def parse_experience(text: str | None) -> tuple[int, int]:
    """Parse '3-8 Yrs', '5+ years', '2 to 4 years', 'Fresher' -> (min, max).

    Returns (-1, -1) when unknown and uses 99 for open-ended "N+".
    """
    if not text:
        return -1, -1
    t = str(text)
    if re.search(r"\bfresher|\bentry[- ]level|\b0\s*yrs?\b", t, re.I) and not _RANGE_RE.search(t):
        return 0, 1
    m = _RANGE_RE.search(t)
    if m:
        lo, hi = int(float(m.group(1))), int(float(m.group(2)))
        if lo > hi:
            lo, hi = hi, lo
        if hi <= 40:
            return lo, hi
    m = _PLUS_RE.search(t)
    if m:
        return int(m.group(1)), OPEN_ENDED
    m = _MIN_RE.search(t)
    if m:
        return int(m.group(1)), OPEN_ENDED
    m = _SINGLE_RE.search(t)
    if m and int(m.group(1)) <= 40:
        n = int(m.group(1))
        return n, n
    return -1, -1


def coerce_int(value: Any, default: int = -1) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------- recency

_AGO_RE = re.compile(r"(\d+)\s*\+?\s*(minute|min|hour|hr|day|week|month|year)s?", re.I)


def parse_posted_days(text: str | None) -> int:
    """'3 Days Ago', 'Just posted', 'Today', '30+ days ago', '2 weeks ago' -> days (int).

    -1 when unknown.
    """
    if not text:
        return -1
    t = str(text).strip().lower()
    if any(w in t for w in ("just now", "just posted", "today", "few hours", "moments ago", "hour ago", "hours ago", "minutes ago")):
        return 0
    if "yesterday" in t:
        return 1
    m = _AGO_RE.search(t)
    if not m:
        return -1
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith(("minute", "min", "hour", "hr")):
        return 0
    if unit.startswith("day"):
        return n
    if unit.startswith("week"):
        return n * 7
    if unit.startswith("month"):
        return n * 30
    if unit.startswith("year"):
        return n * 365
    return -1


def days_since_epoch_ms(ms: Any, now: float | None = None) -> int:
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return -1
    if ms <= 0:
        return -1
    now = time.time() if now is None else now
    return max(0, int((now - ms / 1000.0) // 86400))


# -------------------------------------------------------------------- skills

def split_skills(value: Any) -> list[str]:
    """Accept a list, or a comma / pipe / semicolon separated string."""
    if not value:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,|;\n•]+", value)
    elif isinstance(value, (list, tuple, set)):
        parts = []
        for v in value:
            if isinstance(v, dict):
                v = v.get("label") or v.get("name") or ""
            parts.extend(re.split(r"[,|;]+", str(v)))
    else:
        return []
    out, seen = [], set()
    for p in parts:
        p = strip_html(p).strip(" .-")
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


# ---------------------------------------------------------------- dedupe keys

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                    "src", "sid", "xp", "px", "from", "tk", "vjs", "advn", "adid", "ref"}


def canonical_url(url: str) -> str:
    """Lowercase scheme/host, drop fragment, tracking params and trailing slash."""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if k.lower() not in _TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path,
                       urlencode(query), ""))


_COMPANY_SUFFIX_RE = re.compile(
    r"\b(private|pvt|limited|ltd|llp|inc|incorporated|corp|corporation|co|company|"
    r"plc|gmbh|india|technologies|technology|solutions|services)\b\.?", re.I)


def normalize_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)          # drop "(Remote)", "[Urgent]"
    t = re.sub(r"\b(sr|snr)\b\.?", "senior", t)
    t = re.sub(r"\b(jr)\b\.?", "junior", t)
    t = re.sub(r"[^a-z0-9+#]+", " ", t)
    return _WS_RE.sub(" ", t).strip()


def normalize_company(company: str) -> str:
    c = (company or "").lower()
    c = re.sub(r"[^a-z0-9& ]+", " ", c)
    c = _COMPANY_SUFFIX_RE.sub(" ", c)
    return _WS_RE.sub(" ", c).strip()


def title_company_key(job: dict) -> tuple[str, str]:
    return normalize_title(job.get("title", "")), normalize_company(job.get("company", ""))


# ------------------------------------------------------------------- records

def normalize_job(raw: dict, platform: str | None = None) -> dict:
    """Coerce a raw adapter record into the standard job dict shape."""
    job = dict(JOB_FIELDS_DEFAULTS)
    job.update({k: v for k, v in (raw or {}).items() if v is not None})
    if platform:
        job["platform"] = platform
    for key in ("platform", "job_id", "title", "company", "location", "apply_url"):
        job[key] = strip_html(str(job.get(key) or "")) if key not in ("apply_url",) else str(job.get(key) or "").strip()
    job["platform"] = job["platform"].lower()
    job["description"] = strip_html(job.get("description"), max_len=1500)
    sal = strip_html(str(job.get("salary") or ""))
    job["salary"] = sal if sal and sal.lower() not in ("not disclosed", "none", "null", "-") else NOT_DISCLOSED
    job["skills"] = split_skills(job.get("skills"))
    job["exp_min"] = coerce_int(job.get("exp_min"))
    job["exp_max"] = coerce_int(job.get("exp_max"))
    if job["exp_min"] >= 0 and job["exp_max"] == -1:
        job["exp_max"] = OPEN_ENDED
    if job["exp_max"] >= 0 and job["exp_min"] == -1:
        job["exp_min"] = 0
    if 0 <= job["exp_max"] < job["exp_min"]:
        job["exp_min"], job["exp_max"] = job["exp_max"], job["exp_min"]
    job["posted_days_ago"] = coerce_int(job.get("posted_days_ago"))
    job["easy_apply"] = bool(job.get("easy_apply"))
    for k in ("match_score", "rank_score"):
        try:
            job[k] = float(job.get(k) or 0.0)
        except (TypeError, ValueError):
            job[k] = 0.0
    if not job["company"]:
        job["company"] = "Unknown"
    return job


def dedupe_jobs(jobs: list[dict]) -> list[dict]:
    """Remove duplicates by canonical apply_url and by (normalised title, company).

    When duplicates collide, keep the better one: easy-apply first, then the
    higher rank_score, then the higher match_score. Order of first appearance
    is preserved for the survivors.
    """
    def better(a: dict, b: dict) -> bool:
        ka = (bool(a.get("easy_apply")), float(a.get("rank_score") or 0), float(a.get("match_score") or 0))
        kb = (bool(b.get("easy_apply")), float(b.get("rank_score") or 0), float(b.get("match_score") or 0))
        return ka > kb

    slots: list[dict | None] = []
    by_url: dict[str, int] = {}
    by_tc: dict[tuple[str, str], int] = {}
    for job in jobs:
        url_key = canonical_url(job.get("apply_url", ""))
        tc = title_company_key(job)
        tc_valid = bool(tc[0] and tc[1] and tc[1] != "unknown")
        idx = by_url.get(url_key) if url_key else None
        if idx is None and tc_valid:
            idx = by_tc.get(tc)
            # Same title+company on the SAME platform with a different URL is a
            # separate posting (e.g. another city), so only merge across platforms.
            if idx is not None and slots[idx].get("platform") == job.get("platform"):
                idx = None
                tc_valid = False  # keep the first posting as the cross-platform anchor
        if idx is None:
            slots.append(job)
            idx = len(slots) - 1
        elif better(job, slots[idx]):
            old = slots[idx]
            slots[idx] = job
            # keep the old keys pointing to this slot as well
            old_url = canonical_url(old.get("apply_url", ""))
            if old_url:
                by_url[old_url] = idx
        if url_key:
            by_url[url_key] = idx
        if tc_valid:
            by_tc[tc] = idx
    return [j for j in slots if j is not None]
