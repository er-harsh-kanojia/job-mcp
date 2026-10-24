"""Mock interview ("Practise with Claude / ChatGPT") for one prep question.

The model plays the interviewer: it asks the question, asks up to two follow-ups,
then closes with feedback. Feedback is emitted by the model inside a
``<feedback>{json}</feedback>`` block at the end of its closing message; that
block is stripped from the streamed text and parsed (with a structured-output
fallback call if it is missing or malformed).

The resume + question context is a hidden first user turn, marked as the
cache prefix, so every turn of the session reuses it. Works with either provider.
"""

from __future__ import annotations

import json
import logging
import re
from typing import AsyncIterator

from pydantic import BaseModel, Field, ValidationError, field_validator

from . import llm, store
from .extract import ResumeError
from .review import load_resume

log = logging.getLogger("job_mcp.ai.interview")

MAX_FOLLOWUPS = 2
FORCE_FEEDBACK_AFTER = MAX_FOLLOWUPS + 1   # candidate answers
TAG = "<feedback>"
ROUND_NAMES = {"llm": "LLM / GenAI", "design": "system design", "fund": "ML fundamentals",
               "code": "coding", "behav": "behavioural"}


class Feedback(BaseModel):
    score: int = Field(ge=1, le=10)
    strengths: list[str]
    improve: list[str]

    @field_validator("score", mode="before")
    @classmethod
    def _clamp(cls, v):
        try:
            return max(1, min(10, round(float(v))))
        except (TypeError, ValueError):
            return v


class SessionError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def system_prompt(role: str) -> str:
    return f"""You are a senior interviewer at an Indian tech company, hiring for a "{role}" role. You are \
running a realistic one-question mock interview over text chat with the candidate whose resume you have.

How the interview runs:
- Your first message: one short greeting line, then ask the interview question (you may rephrase it \
slightly to sound natural). Nothing else.
- After each answer, ask exactly one focused follow-up that probes depth: trade-offs, specifics, numbers, \
failure cases, or what they personally did. Tie it to their resume where you can. Ask at most \
{MAX_FOLLOWUPS} follow-ups in total.
- After the candidate answers your last follow-up (or earlier if they ask to stop or clearly can't go \
further), end the interview: write one or two closing sentences, then on its own line the feedback block, \
exactly in this form:
<feedback>{{"score": <integer 1-10>, "strengths": ["..."], "improve": ["..."]}}</feedback>
  score is how strong the whole answer was for this role and level; give 2-4 specific strengths and 2-4 \
specific improvements, based only on what the candidate actually said. Where their resume holds real \
evidence they didn't use, point to it. Never invent experience for them.
- Keep every message under 120 words, plain conversational text, no markdown headings. Don't reveal the \
model answer before the feedback."""


def _intro_turn(resume_text: str, question: dict) -> dict:
    qctx = {"round": ROUND_NAMES.get(question.get("round", ""), question.get("round", "")),
            "question": question.get("q", ""),
            "why_interviewers_ask": question.get("why", ""),
            "strong_answer_outline": question.get("outline", []),
            "resume_evidence_hint": question.get("from_resume", "")}
    return {"role": "user", "content": [
        llm.text_part(f"<resume>\n{resume_text}\n</resume>\n\n<interview_question>\n"
                      f"{json.dumps(qctx, ensure_ascii=False, indent=1)}\n</interview_question>", cache=True),
        llm.text_part("Start the interview now.")]}


def _api_messages(resume_text: str, question: dict, history: list[dict], final_note: bool) -> list[dict]:
    msgs = [_intro_turn(resume_text, question)]
    for i, m in enumerate(history):
        content = m["content"]
        if final_note and i == len(history) - 1 and m["role"] == "user":
            content = [llm.text_part(content),
                       llm.text_part("(Practice app note: that was the candidate's answer to your last "
                                     "follow-up. Close the interview now with the feedback block.)")]
        msgs.append({"role": m["role"], "content": content})
    return msgs


def _partial_tag_len(text: str) -> int:
    """Length of the longest suffix of text that is a proper prefix of '<feedback'."""
    for k in range(min(len(TAG) - 1, len(text)), 0, -1):
        if TAG.startswith(text[-k:]):
            return k
    return 0


def parse_feedback(raw: str) -> tuple[str, Feedback | None]:
    """(visible text, feedback or None) from a full assistant reply."""
    idx = raw.find("<feedback")
    if idx < 0:
        return raw.strip(), None
    visible = raw[:idx].strip()
    m = re.search(r"<feedback>\s*(\{.*\})\s*(?:</feedback>|$)", raw[idx:], re.S)
    if not m:
        return visible, None
    try:
        return visible, Feedback.model_validate(json.loads(m.group(1)))
    except (json.JSONDecodeError, ValidationError):
        return visible, None


def _context(question_id: str) -> tuple[dict, int, str]:
    found = store.get_question(question_id)
    if found is None:
        raise SessionError("not_found", "Unknown question id.", 404)
    question, review_id = found
    resume_text = store.review_resume_text(review_id)
    if not resume_text:
        try:
            resume_text = load_resume()["text"]
        except ResumeError:
            resume_text = "(resume not available)"
    return question, review_id, resume_text


async def start_session(question_id: str, role: str) -> dict:
    """Create a session; the model opens with the question. Returns {session_id, messages}."""
    llm.require()
    question, review_id, resume_text = _context(question_id)
    role = role or ""
    opening = await llm.complete_text(system=system_prompt(role),
                                      messages=_api_messages(resume_text, question, [], False),
                                      max_tokens=1500)
    visible, _ = parse_feedback(opening)
    messages = [{"role": "assistant", "content": visible or question.get("q", "")}]
    sess = store.create_session(question_id, role, review_id, messages)
    return {"session_id": sess["session_id"], "messages": sess["messages"]}


async def _fallback_feedback(role: str, resume_text: str, question: dict, history: list[dict]) -> Feedback:
    transcript = "\n\n".join(f"{'Interviewer' if m['role'] == 'assistant' else 'Candidate'}: {m['content']}"
                             for m in history)
    fb, _ = await llm.structured(
        Feedback, kind="chat", max_tokens=3000, system=system_prompt(role),
        messages=[{"role": "user", "content": [
            _intro_turn(resume_text, question)["content"][0],
            llm.text_part(f"<transcript>\n{transcript}\n</transcript>\n\nThe interview is over. "
                          "Give the feedback: score 1-10, 2-4 strengths, 2-4 improvements.")]}])
    return fb


async def reply(session_id: str, content: str) -> AsyncIterator[tuple[str, dict]]:
    """Stream the interviewer's next turn. Yields ("delta", {"text"}) ... then ("done", {...})."""
    sess = store.get_session(session_id)
    if sess is None:
        raise SessionError("not_found", "Unknown interview session.", 404)
    if sess["feedback"] is not None:
        raise SessionError("interview_finished", "This practice session is finished. Start a new one.", 409)
    content = (content or "").strip()
    if not content:
        raise SessionError("validation", "Message is empty.", 422)
    llm.require()
    question, _, resume_text = _context(sess["question_id"])
    role = sess.get("role") or ""
    history = sess["messages"] + [{"role": "user", "content": content}]
    answers = sum(1 for m in history if m["role"] == "user")
    force = answers >= FORCE_FEEDBACK_AFTER

    raw, emitted, hidden = "", 0, False
    async for d in llm.stream_text(system=system_prompt(role), max_tokens=3000,
                                   messages=_api_messages(resume_text, question, history, force)):
        raw += d
        if hidden:
            continue
        cut = raw.find("<feedback")
        if cut >= 0:
            hidden = True
            end = cut
        else:
            end = len(raw) - _partial_tag_len(raw)
        if end > emitted:
            yield "delta", {"text": raw[emitted:end]}
            emitted = end
    if not hidden and emitted < len(raw):
        yield "delta", {"text": raw[emitted:]}

    visible, feedback = parse_feedback(raw)
    if feedback is None and (hidden or force):
        try:
            feedback = await _fallback_feedback(role, resume_text, question, history + [
                {"role": "assistant", "content": visible}])
        except llm.AIError as exc:
            log.warning("interview: feedback fallback failed: %s", exc.message)
    if not visible:
        visible = "Thanks, that's the end of this practice round." if feedback else "..."
    message = {"role": "assistant", "content": visible}
    history.append(message)
    fb = feedback.model_dump() if feedback else None
    store.update_session(session_id, history, fb)
    if fb is not None:
        store.set_question_practised(sess["question_id"], True)
    done = {"message": message}
    if fb is not None:
        done["feedback"] = fb
    yield "done", done
