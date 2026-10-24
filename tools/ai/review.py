"""Resume review + interview prep for a target role (Claude or ChatGPT).

Pipeline (the four UI steps):
  0. "Reading <file>"                       extract text, number the lines
  1. "Checking facts against your profile"  AI: sections, base scores, issues
  2. "Comparing with N matched <role> jobs" count skill demand in jobs_cache
  3. "Writing suggestions and a prep plan"  AI: demand classes, 2-week plan, questions

The prompts are shared by both providers. The resume + profile block is
identical in both calls and comes first (marked as a cache prefix), so the
second call and any retry read it from the provider's prompt cache.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, field_validator

from .. import tracker
from ..config import get_profile, resume_path
from . import llm, store
from .demand import normalize_skill, skill_demand
from .extract import ResumeError, extract_resume, number_lines

log = logging.getLogger("job_mcp.ai.review")

MIN_JOBS_FOR_COUNTS = 5

# ------------------------------------------------------------------ schemas


def _clamp(lo: float, hi: float):
    def f(v):
        try:
            return max(lo, min(hi, round(float(v))))
        except (TypeError, ValueError):
            return v  # let pydantic report it
    return f


class ScoreSet(BaseModel):
    accuracy: int = Field(ge=0, le=100)
    ats: int = Field(ge=0, le=100)
    fit: int = Field(ge=0, le=100)
    impact: int = Field(ge=0, le=100)

    _c = field_validator("*", mode="before")(lambda v: _clamp(0, 100)(v))


class GainSet(BaseModel):
    accuracy: int = Field(ge=0, le=30, description="points this fix adds to accuracy; 0 if none")
    ats: int = Field(ge=0, le=30)
    fit: int = Field(ge=0, le=30)
    impact: int = Field(ge=0, le=30)

    _c = field_validator("*", mode="before")(lambda v: _clamp(0, 30)(v))


class LineOut(BaseModel):
    id: str = Field(description="the Lnnn id of the line, exactly as given")
    text: str
    kind: Literal["name", "role", "text", "bullet"]


class SectionOut(BaseModel):
    title: str
    lines: list[LineOut]


class IssueOut(BaseModel):
    severity: Literal["mistake", "change", "polish"]
    title: str
    where: str
    why: str
    before: str
    after: str
    note: str
    gain: GainSet
    line_ids: list[str]


class ReviewOut(BaseModel):
    sections: list[SectionOut]
    scores: ScoreSet
    issues: list[IssueOut]


class DemandOut(BaseModel):
    skill: str
    jobs: int = Field(ge=0)
    you: Literal["strong", "some", "gap"]


class PlanOut(BaseModel):
    week: Literal[1, 2]
    text: str
    type: Literal["Resume", "Learn", "Build", "Practice"]
    time: str
    hours: float = Field(ge=0, le=40)

    @field_validator("hours", mode="before")
    @classmethod
    def _hours(cls, v):
        try:
            return max(0.0, min(40.0, float(v)))
        except (TypeError, ValueError):
            return v


class QuestionOut(BaseModel):
    round: Literal["llm", "design", "fund", "code", "behav"]
    q: str
    why: str
    outline: list[str]
    from_resume: str


class PrepOut(BaseModel):
    demand: list[DemandOut]
    plan: list[PlanOut]
    questions: list[QuestionOut]
    note: str


class PrevOutcomeOut(BaseModel):
    n: int = Field(description="number of the previous issue, as listed")
    outcome: Literal["resolved", "partly", "still_open", "not_applicable"]
    evidence: str


class CompareOut(BaseModel):
    summary: str
    changes: list[str]
    previous: list[PrevOutcomeOut]
    new_problems: list[int] = Field(description="numbers of NEW issues introduced by the changes")


# ------------------------------------------------------------------ prompts

SYSTEM_PROMPT = """You are an expert resume reviewer and interview coach for AI/ML and software engineers \
in the Indian job market (Naukri, Instahyre, Indeed India, LinkedIn). You review the candidate's resume \
against their own profile data and a target role, and you prepare them for interviews.

Ground rules, which apply to every answer:
- Never invent experience, employers, projects, dates, metrics, tools or achievements. Every rewrite must \
use only facts already in the resume or the profile. Where a number would make a bullet stronger, use a \
placeholder such as [X%] or [N users] for the candidate to fill in.
- When suggesting a skill or keyword the resume does not show, say plainly: "Only add this if you've \
actually used it."
- CTC / salary figures are irrelevant to the review; ignore them.
- Be specific: quote the exact text you are talking about. Prefer a few high-value findings over many \
trivial ones.
- Write in clear, plain English (Indian English spelling is fine)."""


def _profile_facts(profile: dict) -> dict:
    af = profile.get("autofill") or {}
    keep = ("total_experience", "highest_qualification", "graduation_year", "last_working_day",
            "notice_period", "primary_cloud")
    return {
        "name": profile.get("name") or "",
        "email": profile.get("email") or "",
        "phone": profile.get("phone") or "",
        "location": profile.get("location") or "",
        "experience_years": profile.get("experience_years") or 0,
        **{k: af.get(k, "") for k in keep},
        "years_per_skill": af.get("experience") or {},
        "preferred_locations": af.get("preferred_locations") or [],
    }


def context_block(numbered_resume: str, profile: dict, filename: str, pages: int, words: int) -> dict:
    """The cached, reused part of every analysis request (resume + profile), as a neutral text part."""
    facts = json.dumps(_profile_facts(profile), sort_keys=True, ensure_ascii=False, indent=1)
    text = (f"<resume filename=\"{filename}\" pages=\"{pages}\" words=\"{words}\">\n"
            f"{numbered_resume}\n</resume>\n\n"
            f"<profile source=\"the candidate's saved application profile (treat as ground truth for "
            f"contact details, experience years and education)\">\n{facts}\n</profile>")
    return llm.text_part(text, cache=True)


REVIEW_TASK = """Today is {today}. Target role: "{role}".

Review the resume above for this target role and return JSON with:

1. sections: the resume as sections in reading order (the contact header first, title "Header" if it has \
none). Each line keeps the id it has above (Lnnn). If a line is just a wrapped continuation of the previous \
line, merge it into that line and keep the first id. Only fix extraction artefacts (broken hyphenation, \
stray spaces); never reword. kind: "name" for the candidate's name, "role" for a job title / company / \
dates heading, "bullet" for bullet points, "text" for everything else. Do not drop any content.

2. scores, 0-100, for the resume as it stands:
   - accuracy: consistent with the profile and with itself; no typos or factual slips
   - ats: parseable structure, standard headings, the keywords a "{role}" posting expects
   - fit: how well the experience shown matches a "{role}" role
   - impact: results and ownership shown (quantified outcomes) rather than duties

3. issues, most important first (typically 8-15). Check in particular:
   - phone, email and years of experience against the profile (the profile is right; CTC is irrelevant)
   - typos and grammar slips
   - date ranges that overlap, are impossible, or don't add up to the claimed experience
   - a generic or missing summary for the target role
   - bullets that describe duties instead of results
   - skills-list bloat: tools listed but not evidenced anywhere else
   - page length (this resume: {pages} page(s), {words} words; aim for 1-2 pages at this experience level)
   - keywords a "{role}" role usually expects that are missing (note: "Only add this if you've actually used it.")
   severity: "mistake" = an error a recruiter would notice (wrong contact detail, typo, inconsistent \
dates/experience); "change" = a substantive improvement; "polish" = minor.
   For each issue: title (short), where (section and line, in words), why (1-2 sentences), before (the \
exact current text; "" if something is missing), after (the suggested replacement, facts only, \
placeholders for unknown numbers), note (caveats, "" if none), gain (points each score would rise if \
fixed, 0 where it doesn't help, usually 1-8), line_ids (ids of the lines it concerns; [] if none)."""


PREP_TASK = """Today is {today}. Target role: "{role}".

{demand_instructions}

Resume issues already found (for "Resume" plan items):
{issue_titles}

Return JSON with:
- demand: {demand_shape}
  you: "strong" = clearly evidenced in the resume with real use; "some" = mentioned or lightly used; \
"gap" = not shown.
- plan: a two-week preparation plan of 8-12 items (week 1 or 2), about 10-12 hours per week in total. \
type: "Resume" (apply the most valuable resume fixes first), "Learn" (close the biggest demand gaps), \
"Build" (a small portfolio piece that proves a gap skill), "Practice" (rehearse the questions below). \
time: when to do it, e.g. "Days 1-2" or "Weekend". hours: estimated hours. text: one concrete action.
- questions: 12-16 likely interview questions for this role at Indian companies, at least two per round: \
"llm" (LLM / GenAI concepts), "design" (ML or LLM system design), "fund" (ML fundamentals), "code" \
(Python / coding), "behav" (behavioural). For each: q, why (why it's likely for this candidate and role), \
outline (3-5 short points of a strong answer), from_resume (which specific project or line of the resume \
to use as evidence, and how; if nothing in the resume is relevant, say so honestly and suggest how to \
answer without overclaiming).
- note: one sentence on what the demand figures are based on."""


COMPARE_TASK = """Today is {today}. Target role: "{role}".

The resume above is the candidate's NEW version. Below is their PREVIOUS resume and the review of it \
from {prev_date} (target role then: "{prev_role}"). Compare the two so the candidate can see whether \
their edits worked.

<previous_resume filename="{prev_file}">
{prev_text}
</previous_resume>

Previous scores (0-100): {prev_scores}
Previous issues (status = what the candidate marked in the app; "fixed" is only their claim, check it):
{prev_issues}

Issues found in the NEW resume:
{new_issues}

Return JSON with:
- summary: 2-3 sentences on what improved, what didn't, and the net effect for a "{role}" role.
- changes: up to 10 concrete changes between the previous and the new resume, one short line each \
(quote the text where it helps). Only real differences; [] if the text is effectively the same.
- previous: one entry per previous issue, n = its number above. outcome: "resolved" (the new resume fixes \
it), "partly" (improved but not fully), "still_open" (the problem is still there), "not_applicable" (that \
content was removed or the issue no longer applies). evidence: one short sentence, quoting the new text.
- new_problems: the numbers of NEW-resume issues that were introduced by the changes (not present in the \
previous resume). [] if none."""

MAX_PREV_CHARS = 20_000


def _same_text(a: str, b: str) -> bool:
    return " ".join((a or "").split()) == " ".join((b or "").split())


def _base_overall(scores: dict) -> int:
    vals = [max(0.0, min(100.0, float(scores.get(k) or 0))) for k in store.SCORE_KEYS]
    return int(sum(vals) / len(vals) + 0.5)


async def _compare(ctx: dict, prev: dict, prev_text: str, new_text: str, role: str, today: str,
                   scores: dict, issues: list[dict]) -> dict:
    """Comparison of the new analysis with a previous review (AI call unless the text is unchanged)."""
    base = {
        "previous_review_id": prev["id"],
        "previous_analysed_at": prev["analysed_at"],
        "previous_filename": prev.get("resume_filename") or "",
        "previous_role": prev.get("target_role") or "",
        "scores_before": prev["scores"],
        "scores_after": scores,
        "overall_before": _base_overall(prev["scores"]),
        "overall_after": _base_overall(scores),
    }
    prev_issues = prev.get("issues") or []
    if _same_text(prev_text, new_text):
        return {**base, "identical_resume": True,
                "summary": "This is the same resume text as the previous report, so nothing has changed yet. "
                           "Edit the file and upload it again to see your progress.",
                "changes": [], "new_problem_numbers": [],
                "previous": [{"title": i["title"], "severity": i["severity"], "previous_status": i["status"],
                              "outcome": "still_open", "evidence": "Unchanged resume."} for i in prev_issues]}

    def fmt_prev(n: int, i: dict) -> str:
        return (f"{n}. [{i['severity']}] {i['title']} (status: {i['status']})\n"
                f"   was: {i.get('before') or '(missing)'}\n   suggested: {i.get('after') or '-'}")
    prev_block = "\n".join(fmt_prev(n, i) for n, i in enumerate(prev_issues, 1)) or "(none)"
    new_block = "\n".join(f"{n}. [{i['severity']}] {i['title']}: {i.get('before') or '(missing)'}"
                          for n, i in enumerate(issues, 1)) or "(none)"
    out, _ = await llm.structured(
        CompareOut, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [ctx, llm.text_part(COMPARE_TASK.format(
            today=today, role=role, prev_date=prev["analysed_at"][:10], prev_role=prev.get("target_role") or role,
            prev_file=prev.get("resume_filename") or "resume", prev_text=prev_text[:MAX_PREV_CHARS],
            prev_scores=json.dumps(prev["scores"]), prev_issues=prev_block, new_issues=new_block))]}],
        max_tokens=8000)
    by_n = {o.n: o for o in out.previous}
    previous = []
    for n, i in enumerate(prev_issues, 1):
        o = by_n.get(n)
        previous.append({"title": i["title"], "severity": i["severity"], "previous_status": i["status"],
                         "outcome": o.outcome if o else "still_open",
                         "evidence": (o.evidence.strip() if o else "") or ""})
    return {**base, "identical_resume": False, "summary": out.summary.strip(),
            "changes": [c.strip() for c in out.changes if c.strip()][:10],
            "previous": previous,
            "new_problem_numbers": sorted({n for n in out.new_problems if 1 <= n <= len(issues)})}


def _demand_instructions(demand: dict, role: str) -> tuple[str, str, str]:
    """(instructions, demand_shape, source)"""
    n = demand["matched_jobs"]
    if n >= MIN_JOBS_FOR_COUNTS and demand["rows"]:
        rows = "\n".join(f"- {r['skill']}: {r['jobs']} of {n} jobs" for r in demand["rows"])
        return (f"Skill demand counted from {n} recent \"{role}\" job postings the candidate's searches found:\n"
                f"{rows}",
                "one row per skill listed above, in the same order, with skill and jobs copied exactly as given "
                "and you set from the resume.",
                "jobs")
    return (f"Only {n} matching job posting(s) are cached locally, which is too few to count. Estimate "
            f"typical skill demand for \"{role}\" roles in India from your own knowledge instead.",
            "the 12-15 skills most often required for this role; jobs = your estimate of how many out of 100 "
            "typical postings ask for it.",
            "estimate")


# ------------------------------------------------------------------ pipeline

StepCallback = Callable[[dict], Any]


async def _emit(cb: StepCallback | None, ev: dict) -> None:
    if cb is None:
        return
    res = cb(ev)
    if inspect.isawaitable(res):
        await res


def step_labels(filename: str, role: str, matched: int, prev_date: str | None = None) -> list[str]:
    check = "Checking facts against your profile"
    if prev_date:
        check += f" and your report from {prev_date}"
    return [f"Reading {filename}", check,
            f"Comparing with {matched} matched {role} jobs", "Writing suggestions and a prep plan"]


def load_resume() -> dict:
    """Extract the configured resume; raises ResumeError."""
    p = resume_path()
    if p is None:
        raise ResumeError("resume_missing", "No resume found. Upload one in Profile (PDF or DOCX).")
    return extract_resume(p)


def _check_review(known_ids: set[str]):
    def check(out: ReviewOut) -> None:
        ids = [ln.id for s in out.sections for ln in s.lines]
        if not ids:
            raise ValueError("no resume lines returned")
        unknown = [i for i in ids if i not in known_ids]
        if len(unknown) > max(3, len(ids) // 4):
            raise ValueError(f"{len(unknown)} line ids are not from the resume")
    return check


def _clean_review(out: ReviewOut, known: dict[str, str]) -> tuple[list[dict], list[dict], dict]:
    sections, seen = [], set()
    for s in out.sections:
        lines = []
        for ln in s.lines:
            lid = ln.id.strip()
            if lid not in known or lid in seen:
                continue  # invented or duplicated id: drop the line rather than break highlights
            seen.add(lid)
            lines.append({"id": lid, "text": ln.text.strip() or known[lid], "kind": ln.kind})
        if lines:
            sections.append({"title": s.title.strip(), "lines": lines})
    issues = []
    for it in out.issues:
        d = it.model_dump()
        d["gain"] = {k: v for k, v in d["gain"].items() if v}
        d["line_ids"] = [i for i in dict.fromkeys(d["line_ids"]) if i in seen]
        issues.append(d)
    return sections, issues, out.scores.model_dump()


def _fallback_you(skill_key: str, resume_text: str, profile: dict) -> str:
    exp = {normalize_skill(k): v for k, v in ((profile.get("autofill") or {}).get("experience") or {}).items()}
    if skill_key in exp:
        return "some"
    return "some" if re.search(r"(?<![a-z0-9])" + re.escape(skill_key) + r"(?![a-z0-9])",
                               resume_text.lower()) else "gap"


def _merge_demand(prep: PrepOut, demand: dict, source: str, resume_text: str, profile: dict) -> list[dict]:
    if source == "estimate":
        return [{"skill": r.skill, "jobs": int(r.jobs), "you": r.you} for r in prep.demand]
    by_name = {normalize_skill(r.skill): r.you for r in prep.demand}
    rows = []
    for r in demand["rows"]:
        you = by_name.get(r["key"]) or by_name.get(normalize_skill(r["skill"]))
        rows.append({"skill": r["skill"], "jobs": r["jobs"],
                     "you": you or _fallback_you(r["key"], resume_text, profile)})
    return rows


async def run_analysis(target_role: str, on_step: StepCallback | None = None,
                       compare_to: int | None = None) -> dict:
    """Run the 4-step analysis, store it, and return the Review dict.

    compare_to: a previous review id to compare with; None = the latest previous
    report (same role first); 0 = don't compare.
    Raises ResumeError (no/unsupported resume), llm.AINotConfigured, llm.AIError.
    """
    target_role = " ".join((target_role or "").split())
    if not target_role:
        raise ValueError("target_role is required")
    prov = llm.require()
    profile = get_profile()
    p = resume_path()
    filename = p.name if p else "resume"
    demand = skill_demand(tracker.cached_jobs(days=90), target_role)
    prev = (None if compare_to == 0 else
            store.get_review_by_id(compare_to) if compare_to else store.previous_review(target_role))
    labels = step_labels(filename, target_role, demand["matched_jobs"],
                         prev["analysed_at"][:10] if prev else None)

    async def step(i: int, state: str) -> None:
        await _emit(on_step, {"index": i, "label": labels[i], "state": state})

    # 0. read
    await step(0, "running")
    resume = load_resume()
    numbered, known = number_lines(resume["text"])
    ctx = context_block(numbered, profile, resume["filename"], resume["pages"], resume["words"])
    today = date.today().isoformat()
    await step(0, "done")

    # 1. facts, scores, issues
    await step(1, "running")
    review_out, model_used = await llm.structured(
        ReviewOut, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [
            ctx, llm.text_part(REVIEW_TASK.format(
                today=today, role=target_role, pages=resume["pages"], words=resume["words"]))]}],
        check=_check_review(set(known)))
    sections, issues, scores = _clean_review(review_out, known)
    comparison = None
    if prev:
        try:
            comparison = await _compare(ctx, prev, store.review_resume_text(prev["id"]), resume["text"],
                                        target_role, today, scores, issues)
        except llm.AIError as exc:
            # A failed comparison shouldn't lose the review itself.
            log.warning("review: comparison with report %s failed: %s", prev["id"], exc)
    await step(1, "done")

    # 2. demand (local)
    await step(2, "running")
    instructions, shape, source = _demand_instructions(demand, target_role)
    await step(2, "done")

    # 3. prep
    await step(3, "running")
    titles = "\n".join(f"- [{i['severity']}] {i['title']}" for i in issues[:12]) or "- (none)"
    prep_out, _ = await llm.structured(
        PrepOut, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [
            ctx, llm.text_part(PREP_TASK.format(
                today=today, role=target_role, demand_instructions=instructions,
                issue_titles=titles, demand_shape=shape))]}])
    demand_rows = _merge_demand(prep_out, demand, source, resume["text"], profile)
    prep = {
        "matched_jobs": demand["matched_jobs"],
        "demand": demand_rows,
        "demand_source": source,
        "demand_scale": demand["matched_jobs"] if source == "jobs" else 100,
        "note": prep_out.note.strip() or (
            f"Counted from {demand['matched_jobs']} cached job postings." if source == "jobs" else
            f"Too few cached jobs to count; these are {prov.short}'s estimates per 100 typical postings."),
        "plan": [pi.model_dump() for pi in prep_out.plan],
        "questions": [q.model_dump() for q in prep_out.questions],
    }
    review = store.save_review(target_role=target_role, resume_filename=resume["filename"],
                               model=model_used, scores=scores, sections=sections, issues=issues,
                               prep=prep, resume_text=resume["text"],
                               extra={"provider": prov.id, **({"comparison": comparison} if comparison else {})})
    await step(3, "done")
    return review


def offline_context(target_role: str) -> dict:
    """What the MCP tools return when no API key is configured: the extracted
    resume, the profile facts and local demand counts, so the MCP client (Claude)
    can do the review itself."""
    profile = get_profile()
    out: dict[str, Any] = {"ai_configured": False, "target_role": target_role,
                           "instructions": ("No AI API key is configured in Job MCP, so do the review "
                                            "yourself from the resume text and profile below. Never invent "
                                            "experience; missing skills are 'only add if you've used it'."),
                           "profile": _profile_facts(profile)}
    try:
        r = load_resume()
        out["resume"] = {"filename": r["filename"], "pages": r["pages"], "words": r["words"], "text": r["text"]}
    except ResumeError as exc:
        out["resume"] = None
        out["resume_error"] = exc.message
    out["demand"] = skill_demand(tracker.cached_jobs(days=90), target_role) if target_role else None
    return out


def resume_file_info(path: Path | None) -> dict | None:
    if path is None or not path.is_file():
        return None
    from datetime import datetime
    st = path.stat()
    return {"filename": path.name, "size_bytes": st.st_size,
            "uploaded_at": datetime.fromtimestamp(st.st_mtime).astimezone().replace(microsecond=0).isoformat()}
