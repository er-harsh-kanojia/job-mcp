"""Autopilot: scheduled search + apply with per-platform daily caps.

Settings live in config.json under ``"autopilot"`` (see DEFAULTS). Each run:
search every keyword on the chosen platforms -> keep good matches (match score,
Easy Apply, not applied yet, experience fits, company not excluded) -> take the
best ones up to each platform's remaining daily cap -> bulk apply.

Runs are logged in the tracker DB (``autopilot_runs``) so a time slot runs at
most once a day. The scheduler loop itself lives in api/autopilot.py.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterator

from . import tracker
from .config import get_excluded_companies, get_experience_years, get_profile, update_config
from .platforms import SUPPORTED_PLATFORMS, get_adapter_class
from .scoring import experience_incompatible
from .search import is_company_excluded

DEFAULT_KEYWORDS = ["AI/ML Engineer", "ML Engineer", "AI Engineer", "Python AI Engineer", "AI Cloud Engineer",
                    "GenAI Engineer", "LLM Engineer", "Deep Learning Engineer"]
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "live": False,                       # False = dry run (fills forms, never submits)
    "times": ["09:30", "18:30"],         # local time slots
    "platforms": ["naukri", "instahyre", "hirist"],
    "keywords": DEFAULT_KEYWORDS,
    "location": "India",
    "min_score": 0.7,
    "daily_caps": {"naukri": 80, "instahyre": 60, "hirist": 30},
    "wait_for_me": False,                # True: wait up to 3 min for you to answer unknown questions
}
SLOT_WINDOW = timedelta(hours=3)         # a missed slot (laptop off) still runs within 3 h
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS autopilot_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date    TEXT NOT NULL,
    slot        TEXT NOT NULL,
    live        INTEGER NOT NULL,
    status      TEXT NOT NULL,
    task_id     TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    searched    INTEGER NOT NULL DEFAULT 0,
    selected    INTEGER NOT NULL DEFAULT 0,
    applied     INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    skipped     INTEGER NOT NULL DEFAULT 0,
    message     TEXT
);
"""


# ------------------------------------------------------------------ settings

def apply_platforms() -> list[str]:
    """Platforms autopilot can apply on: the ones with a login (public boards are applied to on the site)."""
    out = []
    for p in SUPPORTED_PLATFORMS:
        try:
            if get_adapter_class(p).login_required:
                out.append(p)
        except Exception:
            continue
    return out


def get_config() -> dict:
    raw = get_profile().get("autopilot")
    cfg = {**DEFAULTS, **(raw if isinstance(raw, dict) else {})}
    cfg["daily_caps"] = {**DEFAULTS["daily_caps"], **(cfg.get("daily_caps") or {})}
    return cfg


def validate(cfg: dict) -> dict[str, str]:
    """Field -> message for invalid settings ({} when valid)."""
    errs: dict[str, str] = {}
    times = cfg.get("times") or []
    if not isinstance(times, list) or not times or not all(isinstance(t, str) and _TIME_RE.match(t) for t in times):
        errs["times"] = "Use one or more times like 09:30."
    plats = cfg.get("platforms") or []
    choices = apply_platforms()
    if not plats or any(p not in choices for p in plats):
        errs["platforms"] = f"Choose from: {', '.join(choices)}."
    if not [k for k in (cfg.get("keywords") or []) if str(k).strip()]:
        errs["keywords"] = "Enter at least one keyword."
    try:
        if not 0 <= float(cfg.get("min_score")) <= 1:
            raise ValueError
    except (TypeError, ValueError):
        errs["min_score"] = "Use a number from 0 to 1."
    caps = cfg.get("daily_caps") or {}
    if not isinstance(caps, dict) or any(not isinstance(v, int) or not 0 <= v <= 500 for v in caps.values()):
        errs["daily_caps"] = "Daily limits must be whole numbers from 0 to 500."
    return errs


def save_config(cfg: dict) -> dict:
    keep = {k: cfg[k] for k in DEFAULTS if k in cfg}
    keep["times"] = sorted({t.zfill(5) for t in keep.get("times", DEFAULTS["times"])})
    keep["keywords"] = [k.strip() for k in keep.get("keywords", []) if str(k).strip()]
    update_config({"autopilot": {**get_config(), **keep}})
    return get_config()


# ------------------------------------------------------------------ runs log

@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = tracker.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tracker._lock:
        conn = sqlite3.connect(str(path), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript(_SCHEMA)
            yield conn
            conn.commit()
        finally:
            conn.close()


def _now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def start_run(slot: str, live: bool, task_id: str | None = None, now: datetime | None = None) -> int:
    now = now or _now()
    with _connect() as conn:
        cur = conn.execute("INSERT INTO autopilot_runs (run_date, slot, live, status, task_id, started_at) "
                           "VALUES (?,?,?,?,?,?)",
                           (now.date().isoformat(), slot, int(live), "running", task_id, now.isoformat()))
        return int(cur.lastrowid)


def finish_run(run_id: int, status: str, **counts: Any) -> None:
    fields = {k: v for k, v in counts.items()
              if k in ("searched", "selected", "applied", "failed", "skipped", "message", "task_id")}
    sets = ", ".join(f"{k}=?" for k in fields)
    with _connect() as conn:
        conn.execute(f"UPDATE autopilot_runs SET status=?, finished_at=?{', ' + sets if sets else ''} WHERE id=?",
                     (status, _now().isoformat(), *fields.values(), run_id))


def recent_runs(limit: int = 10) -> list[dict]:
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM autopilot_runs ORDER BY id DESC LIMIT ?", (limit,))]


def mark_interrupted() -> None:
    """Runs left 'running' by a server that stopped are closed as interrupted."""
    with _connect() as conn:
        conn.execute("UPDATE autopilot_runs SET status='interrupted', finished_at=? WHERE status='running'",
                     (_now().isoformat(),))


def _slots_run_today(today: str) -> set[str]:
    with _connect() as conn:
        return {r["slot"] for r in conn.execute("SELECT slot FROM autopilot_runs WHERE run_date=?", (today,))}


def due_slot(cfg: dict, now: datetime | None = None) -> str | None:
    """The scheduled time slot that should run now (passed, within the window, not run today)."""
    now = now or _now()
    done = _slots_run_today(now.date().isoformat())
    for t in sorted(cfg.get("times") or []):
        h, m = (int(x) for x in t.split(":"))
        at = now.replace(hour=h, minute=m, second=0)
        if at <= now < at + SLOT_WINDOW and t not in done:
            return t
    return None


def next_run_at(cfg: dict, now: datetime | None = None) -> str | None:
    if not cfg.get("enabled"):
        return None
    now = now or _now()
    done = _slots_run_today(now.date().isoformat())
    for day in (0, 1):
        for t in sorted(cfg.get("times") or []):
            h, m = (int(x) for x in t.split(":"))
            at = (now + timedelta(days=day)).replace(hour=h, minute=m, second=0)
            if day == 0 and (t in done or at + SLOT_WINDOW <= now):
                continue
            return max(at, now).isoformat()
    return None


# ------------------------------------------------------------------ selection

def done_today(live: bool, now: datetime | None = None) -> dict[str, int]:
    """Applications per platform since local midnight (dry-run results count in dry mode)."""
    today = (now or _now()).date()
    status = "applied" if live else "dry_run"
    out = {p: 0 for p in apply_platforms()}
    for a in tracker.list_applications(days=2, statuses=[status]):
        try:
            when = datetime.fromisoformat(a["applied_at"]).astimezone().date()
        except (TypeError, ValueError):
            continue
        if when == today and a.get("platform") in out:
            out[a["platform"]] += 1
    return out


_WAITING_FOR_YOU = ("needs your answer", "no answer within", "stopped by you")


def _recently_failed(apply_url: str, now: datetime | None = None) -> bool:
    """Tried in the last 24 h without success, for a reason other than waiting for your answer
    (those are retried once you've answered on the Answers page)."""
    last = tracker.last_attempt(apply_url)
    if not last or last["status"] not in ("failed", "skipped"):
        return False
    if (last.get("error") or "").lower().startswith(_WAITING_FOR_YOU):
        return False
    try:
        when = datetime.fromisoformat(last["applied_at"]).astimezone()
    except (TypeError, ValueError):
        return False
    return (now or _now()) - when < timedelta(hours=24)


def select_jobs(jobs: list[dict], cfg: dict, done: dict[str, int]) -> list[dict]:
    """Best matches per platform, up to each platform's remaining cap for today, best first."""
    exp = get_experience_years()
    excluded = get_excluded_companies()
    min_score = float(cfg.get("min_score") or 0)
    caps = cfg.get("daily_caps") or {}
    by_platform: dict[str, list[dict]] = {}
    for j in sorted(jobs, key=lambda j: float(j.get("rank_score") or 0), reverse=True):
        p = (j.get("platform") or "").lower()
        if p not in (cfg.get("platforms") or []):
            continue
        if float(j.get("match_score") or 0) < min_score or not j.get("easy_apply"):
            continue
        if experience_incompatible(j, exp) or is_company_excluded(j.get("company"), excluded):
            continue
        if tracker.has_applied(j.get("apply_url") or "") or _recently_failed(j.get("apply_url") or ""):
            continue
        by_platform.setdefault(p, []).append(j)
    picked: list[dict] = []
    for p, js in by_platform.items():
        room = max(0, int(caps.get(p, 0)) - int(done.get(p, 0)))
        picked.extend(js[:room])
    return sorted(picked, key=lambda j: float(j.get("rank_score") or 0), reverse=True)
