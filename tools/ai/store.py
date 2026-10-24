"""SQLite persistence for resume reviews, prep items and mock interviews.

Lives in the tracker DB (data/applications.db, or JOB_MCP_DB) in its own tables.
Issue / plan / question ids are globally unique ("r12-i3"), so the PATCH
endpoints need no role.
"""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from .. import tracker

SCORE_KEYS = ("accuracy", "ats", "fit", "impact")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resume_reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    role_key        TEXT NOT NULL,
    target_role     TEXT NOT NULL,
    analysed_at     TEXT NOT NULL,
    resume_filename TEXT,
    model           TEXT,
    scores_json     TEXT NOT NULL,
    sections_json   TEXT NOT NULL,
    prep_json       TEXT,
    extra_json      TEXT,
    resume_text     TEXT
);
CREATE INDEX IF NOT EXISTS idx_resume_reviews_role ON resume_reviews(role_key, id);
CREATE TABLE IF NOT EXISTS review_issues (
    id        TEXT PRIMARY KEY,
    review_id INTEGER NOT NULL,
    ord       INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','fixed','dismissed'))
);
CREATE TABLE IF NOT EXISTS review_plan (
    id        TEXT PRIMARY KEY,
    review_id INTEGER NOT NULL,
    ord       INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    done      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS review_questions (
    id        TEXT PRIMARY KEY,
    review_id INTEGER NOT NULL,
    ord       INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    practised INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS interview_sessions (
    id            TEXT PRIMARY KEY,
    question_id   TEXT NOT NULL,
    role          TEXT,
    review_id     INTEGER,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    messages_json TEXT NOT NULL,
    feedback_json TEXT
);
"""


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


def now_local() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def role_key(role: str) -> str:
    return " ".join((role or "").lower().split())


# ----------------------------------------------------------------- scores

def compute_scores(base: dict, issues: list[dict]) -> tuple[int, int]:
    """(overall, projected).

    overall: base + gains of issues marked fixed. projected: base + gains of all
    issues that are not dismissed (i.e. as if every open issue were fixed).
    Each score is capped at 100; the result is the mean of the four, rounded.
    """
    def total(include: set[str]) -> int:
        vals = []
        for k in SCORE_KEYS:
            v = float(base.get(k) or 0)
            for it in issues:
                if it.get("status") in include:
                    v += float((it.get("gain") or {}).get(k) or 0)
            vals.append(max(0.0, min(100.0, v)))
        return int(math.floor(sum(vals) / len(vals) + 0.5))  # round half up
    return total({"fixed"}), total({"fixed", "open"})


# ---------------------------------------------------------------- reviews

def save_review(*, target_role: str, resume_filename: str, model: str, scores: dict,
                sections: list[dict], issues: list[dict], prep: dict | None,
                resume_text: str = "", extra: dict | None = None) -> dict:
    """Store a new review (issues/plan/questions get ids); returns the Review dict."""
    prep = dict(prep) if prep is not None else None
    plan = prep.pop("plan", []) if prep is not None else []
    questions = prep.pop("questions", []) if prep is not None else []
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO resume_reviews (role_key, target_role, analysed_at, resume_filename, model, "
            "scores_json, sections_json, prep_json, extra_json, resume_text) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (role_key(target_role), target_role.strip(), now_local(), resume_filename, model,
             json.dumps(scores), json.dumps(sections), json.dumps(prep) if prep is not None else None,
             json.dumps(extra or {}), resume_text))
        rid = cur.lastrowid
        for n, it in enumerate(issues, 1):
            data = {k: v for k, v in it.items() if k not in ("id", "status")}
            conn.execute("INSERT INTO review_issues (id, review_id, ord, data_json, status) VALUES (?,?,?,?,?)",
                         (f"r{rid}-i{n}", rid, n, json.dumps(data), "open"))
        for n, it in enumerate(plan, 1):
            data = {k: v for k, v in it.items() if k not in ("id", "done")}
            conn.execute("INSERT INTO review_plan (id, review_id, ord, data_json, done) VALUES (?,?,?,?,0)",
                         (f"r{rid}-p{n}", rid, n, json.dumps(data)))
        for n, it in enumerate(questions, 1):
            data = {k: v for k, v in it.items() if k not in ("id", "practised")}
            conn.execute("INSERT INTO review_questions (id, review_id, ord, data_json, practised) "
                         "VALUES (?,?,?,?,0)", (f"r{rid}-q{n}", rid, n, json.dumps(data)))
    return get_review_by_id(rid)  # type: ignore[return-value]


def _issue(row) -> dict:
    d = json.loads(row["data_json"])
    d["id"] = row["id"]
    d["status"] = row["status"]
    return d


def _plan_item(row) -> dict:
    d = json.loads(row["data_json"])
    d["id"] = row["id"]
    d["done"] = bool(row["done"])
    return d


def _question(row) -> dict:
    d = json.loads(row["data_json"])
    d["id"] = row["id"]
    d["practised"] = bool(row["practised"])
    return d


def _assemble(conn, row) -> dict:
    rid = row["id"]
    issues = [_issue(r) for r in conn.execute(
        "SELECT * FROM review_issues WHERE review_id=? ORDER BY ord", (rid,))]
    scores = json.loads(row["scores_json"])
    overall, projected = compute_scores(scores, issues)
    prep = json.loads(row["prep_json"]) if row["prep_json"] else None
    if prep is not None:
        prep["plan"] = [_plan_item(r) for r in conn.execute(
            "SELECT * FROM review_plan WHERE review_id=? ORDER BY ord", (rid,))]
        prep["questions"] = [_question(r) for r in conn.execute(
            "SELECT * FROM review_questions WHERE review_id=? ORDER BY ord", (rid,))]
    review = {
        "id": rid,
        "analysed_at": row["analysed_at"],
        "resume_filename": row["resume_filename"] or "",
        "target_role": row["target_role"],
        "model": row["model"] or "",
        "scores": scores,
        "overall": overall,
        "projected": projected,
        "issues": issues,
        "sections": json.loads(row["sections_json"]),
        "prep": prep,
    }
    review.update(json.loads(row["extra_json"] or "{}"))
    comp = review.get("comparison")
    if isinstance(comp, dict):
        # The AI refers to new problems by their 1-based position; expose issue ids too.
        nums = comp.get("new_problem_numbers") or []
        comp["new_issue_ids"] = [issues[n - 1]["id"] for n in nums
                                 if isinstance(n, int) and 1 <= n <= len(issues)]
    return review


def get_review_by_id(review_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM resume_reviews WHERE id=?", (review_id,)).fetchone()
        return _assemble(conn, row) if row else None


def get_review(role: str) -> dict | None:
    """Latest review for this target role (case/whitespace-insensitive)."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM resume_reviews WHERE role_key=? ORDER BY id DESC LIMIT 1",
                           (role_key(role),)).fetchone()
        return _assemble(conn, row) if row else None


def latest_review() -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM resume_reviews ORDER BY id DESC LIMIT 1").fetchone()
        return _assemble(conn, row) if row else None


def list_reviews(all_history: bool = False) -> list[dict]:
    """Review summaries, newest first: the latest per role, or every review with ``all_history``.

    [{review_id, target_role, analysed_at, overall, projected, resume_filename, compared_to}]
    """
    out = []
    sql = ("SELECT * FROM resume_reviews ORDER BY id DESC" if all_history else
           "SELECT * FROM resume_reviews WHERE id IN "
           "(SELECT MAX(id) FROM resume_reviews GROUP BY role_key) ORDER BY id DESC")
    with _connect() as conn:
        for row in conn.execute(sql).fetchall():
            r = _assemble(conn, row)
            comp = r.get("comparison") or {}
            out.append({"review_id": r["id"], "target_role": r["target_role"], "analysed_at": r["analysed_at"],
                        "overall": r["overall"], "projected": r["projected"],
                        "resume_filename": r["resume_filename"],
                        "compared_to": comp.get("previous_review_id")})
    return out


def previous_review(role: str) -> dict | None:
    """The review a new analysis should be compared with: the latest one for this role,
    else the latest of any role."""
    return get_review(role) or latest_review()


def review_resume_text(review_id: int) -> str:
    with _connect() as conn:
        row = conn.execute("SELECT resume_text FROM resume_reviews WHERE id=?", (review_id,)).fetchone()
    return (row["resume_text"] if row else "") or ""


def set_issue_status(issue_id: str, status: str) -> dict | None:
    """Returns {"overall", "projected", "issue"} or None if the issue doesn't exist."""
    if status not in ("open", "fixed", "dismissed"):
        raise ValueError("status must be open, fixed or dismissed")
    with _connect() as conn:
        row = conn.execute("SELECT * FROM review_issues WHERE id=?", (issue_id,)).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE review_issues SET status=? WHERE id=?", (status, issue_id))
        rid = row["review_id"]
        issues = [_issue(r) for r in conn.execute(
            "SELECT * FROM review_issues WHERE review_id=? ORDER BY ord", (rid,))]
        scores = json.loads(conn.execute("SELECT scores_json FROM resume_reviews WHERE id=?",
                                         (rid,)).fetchone()["scores_json"])
    overall, projected = compute_scores(scores, issues)
    issue = next(i for i in issues if i["id"] == issue_id)
    return {"overall": overall, "projected": projected, "issue": issue}


def set_plan_done(item_id: str, done: bool) -> dict | None:
    with _connect() as conn:
        if conn.execute("UPDATE review_plan SET done=? WHERE id=?", (int(bool(done)), item_id)).rowcount == 0:
            return None
        return _plan_item(conn.execute("SELECT * FROM review_plan WHERE id=?", (item_id,)).fetchone())


def set_question_practised(question_id: str, practised: bool) -> dict | None:
    with _connect() as conn:
        if conn.execute("UPDATE review_questions SET practised=? WHERE id=?",
                        (int(bool(practised)), question_id)).rowcount == 0:
            return None
        return _question(conn.execute("SELECT * FROM review_questions WHERE id=?", (question_id,)).fetchone())


def get_question(question_id: str) -> tuple[dict, int] | None:
    """(question, review_id) or None."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM review_questions WHERE id=?", (question_id,)).fetchone()
    return (_question(row), row["review_id"]) if row else None


# ---------------------------------------------------------------- interviews

def create_session(question_id: str, role: str, review_id: int | None, messages: list[dict]) -> dict:
    sid = uuid.uuid4().hex[:16]
    now = now_local()
    with _connect() as conn:
        conn.execute("INSERT INTO interview_sessions (id, question_id, role, review_id, created_at, updated_at, "
                     "messages_json, feedback_json) VALUES (?,?,?,?,?,?,?,NULL)",
                     (sid, question_id, role, review_id, now, now, json.dumps(messages)))
    return get_session(sid)  # type: ignore[return-value]


def get_session(session_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM interview_sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        return None
    return {"session_id": row["id"], "question_id": row["question_id"], "role": row["role"],
            "review_id": row["review_id"], "created_at": row["created_at"],
            "messages": json.loads(row["messages_json"]),
            "feedback": json.loads(row["feedback_json"]) if row["feedback_json"] else None}


def update_session(session_id: str, messages: list[dict], feedback: dict | None = None) -> None:
    with _connect() as conn:
        if feedback is None:
            conn.execute("UPDATE interview_sessions SET messages_json=?, updated_at=? WHERE id=?",
                         (json.dumps(messages), now_local(), session_id))
        else:
            conn.execute("UPDATE interview_sessions SET messages_json=?, feedback_json=?, updated_at=? WHERE id=?",
                         (json.dumps(messages), json.dumps(feedback), now_local(), session_id))
