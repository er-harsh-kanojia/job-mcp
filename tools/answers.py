"""Answer bank: your own answers to application questions, reused automatically.

* ``answer_bank``: question -> answer. Filled when you answer a chatbot question
  yourself in the browser, or from the Answers page. ``autofill.answer_question``
  checks it before its built-in rules.
* ``pending_questions``: questions the bot couldn't answer (e.g. during an unattended
  autopilot run), waiting for you to answer once on the Answers page.

Questions match on a normalised key (case, punctuation and spacing ignored), so
"How many years of experience do you have in MCP?" and "how many years of
experience do you have in mcp" are the same question. No fuzzy matching: "years
in RAG" must never answer "years in MCP".
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from . import tracker

log = logging.getLogger("job_mcp.answers")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS answer_bank (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    qkey       TEXT NOT NULL UNIQUE,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'you',
    uses       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_questions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    qkey         TEXT NOT NULL UNIQUE,
    question     TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'text',
    options_json TEXT NOT NULL DEFAULT '[]',
    platform     TEXT,
    job_title    TEXT,
    company      TEXT,
    apply_url    TEXT,
    times_seen   INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""


def qkey(question: str) -> str:
    t = re.sub(r"[^a-z0-9+#/. ]+", " ", (question or "").lower())
    return re.sub(r"\s+", " ", t).strip(" .")


def _now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


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


def _answer(row) -> dict:
    return {k: row[k] for k in ("id", "question", "answer", "source", "uses", "created_at", "updated_at")}


def _pending(row) -> dict:
    d = {k: row[k] for k in ("id", "question", "kind", "platform", "job_title", "company", "apply_url",
                             "times_seen", "created_at", "updated_at")}
    d["options"] = json.loads(row["options_json"] or "[]")
    return d


# ------------------------------------------------------------------ answers

def lookup(question: str) -> str | None:
    """Your saved answer for this question, or None. Never raises."""
    key = qkey(question)
    if not key:
        return None
    try:
        with _connect() as conn:
            row = conn.execute("SELECT id, answer FROM answer_bank WHERE qkey=?", (key,)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE answer_bank SET uses = uses + 1 WHERE id=?", (row["id"],))
            return row["answer"]
    except Exception as exc:  # the bank must never break an application
        log.warning("answers: lookup failed: %s", exc)
        return None


def save(question: str, answer: str, source: str = "you") -> dict | None:
    """Add or replace the answer to a question; also clears it from the pending list."""
    key, answer = qkey(question), (answer or "").strip()
    if not key or not answer:
        return None
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO answer_bank (qkey, question, answer, source, created_at, updated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(qkey) DO UPDATE SET answer=excluded.answer, source=excluded.source, "
            "question=excluded.question, updated_at=excluded.updated_at",
            (key, question.strip(), answer, source, now, now))
        conn.execute("DELETE FROM pending_questions WHERE qkey=?", (key,))
        return _answer(conn.execute("SELECT * FROM answer_bank WHERE qkey=?", (key,)).fetchone())


def list_answers() -> list[dict]:
    with _connect() as conn:
        return [_answer(r) for r in conn.execute("SELECT * FROM answer_bank ORDER BY updated_at DESC, id DESC")]


def update(answer_id: int, answer: str) -> dict | None:
    answer = (answer or "").strip()
    if not answer:
        raise ValueError("answer must not be empty")
    with _connect() as conn:
        if conn.execute("UPDATE answer_bank SET answer=?, source='manual', updated_at=? WHERE id=?",
                        (answer, _now(), answer_id)).rowcount == 0:
            return None
        return _answer(conn.execute("SELECT * FROM answer_bank WHERE id=?", (answer_id,)).fetchone())


def delete(answer_id: int) -> bool:
    with _connect() as conn:
        return conn.execute("DELETE FROM answer_bank WHERE id=?", (answer_id,)).rowcount > 0


# ------------------------------------------------------------------ pending

def add_pending(question: str, *, kind: str = "text", options: list[str] | None = None,
                job: dict | None = None) -> None:
    """Remember a question the bot couldn't answer (counts repeats). Never raises."""
    key = qkey(question)
    if not key:
        return
    job = job or {}
    now = _now()
    try:
        with _connect() as conn:
            if conn.execute("SELECT 1 FROM answer_bank WHERE qkey=?", (key,)).fetchone():
                return  # answered meanwhile
            conn.execute(
                "INSERT INTO pending_questions (qkey, question, kind, options_json, platform, job_title, company, "
                "apply_url, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(qkey) DO UPDATE SET times_seen = times_seen + 1, updated_at=excluded.updated_at, "
                "options_json=CASE WHEN excluded.options_json != '[]' THEN excluded.options_json ELSE options_json END",
                (key, question.strip(), kind, json.dumps([o for o in (options or []) if o]),
                 job.get("platform"), job.get("title"), job.get("company"), job.get("apply_url"), now, now))
    except Exception as exc:
        log.warning("answers: could not save pending question: %s", exc)


def list_pending() -> list[dict]:
    with _connect() as conn:
        return [_pending(r) for r in conn.execute(
            "SELECT * FROM pending_questions ORDER BY times_seen DESC, updated_at DESC")]


def resolve_pending(pending_id: int, answer: str) -> dict | None:
    """Answer a pending question: it moves into the answer bank."""
    with _connect() as conn:
        row = conn.execute("SELECT question FROM pending_questions WHERE id=?", (pending_id,)).fetchone()
    if row is None:
        return None
    return save(row["question"], answer, source="manual")


def dismiss_pending(pending_id: int) -> bool:
    with _connect() as conn:
        return conn.execute("DELETE FROM pending_questions WHERE id=?", (pending_id,)).rowcount > 0


def counts() -> dict:
    with _connect() as conn:
        return {"answers": conn.execute("SELECT COUNT(*) FROM answer_bank").fetchone()[0],
                "pending": conn.execute("SELECT COUNT(*) FROM pending_questions").fetchone()[0]}
