"""Match / recency / rank scoring (pure functions, no I/O)."""

from __future__ import annotations

import re
from typing import Iterable

from .normalize import OPEN_ENDED

# Words that say little about the role itself.
STOPWORDS = {
    "and", "or", "the", "a", "an", "of", "for", "in", "with", "to", "at", "on",
    "engineer", "engineering", "developer", "development", "specialist", "role",
    "job", "jobs", "senior", "junior", "lead", "staff", "principal", "sr", "jr",
    "associate", "consultant", "expert", "professional", "ii", "iii", "i",
}

# Canonical tokens: expand common abbreviations so "ML" matches "Machine Learning".
SYNONYMS = {
    "machine learning": "ml",
    "artificial intelligence": "ai",
    "generative ai": "genai",
    "gen ai": "genai",
    "large language model": "llm",
    "large language models": "llm",
    "llms": "llm",
    "natural language processing": "nlp",
    "computer vision": "cv",
    "deep learning": "dl",
    "scikit learn": "sklearn",
    "scikit-learn": "sklearn",
    "retrieval augmented generation": "rag",
    "data scientist": "datascience",
    "data science": "datascience",
    "ml ops": "mlops",
}

LOCATION_ALIASES = {
    "bengaluru": {"bengaluru", "bangalore", "blr"},
    "bangalore": {"bengaluru", "bangalore", "blr"},
    "gurugram": {"gurugram", "gurgaon"},
    "gurgaon": {"gurugram", "gurgaon"},
    "delhi ncr": {"delhi", "new delhi", "ncr", "delhi ncr", "noida", "greater noida",
                  "gurgaon", "gurugram", "ghaziabad", "faridabad"},
    "delhi": {"delhi", "new delhi", "delhi ncr"},
    "noida": {"noida", "greater noida"},
    "mumbai": {"mumbai", "navi mumbai", "thane", "bombay"},
    "hyderabad": {"hyderabad", "secunderabad"},
    "pune": {"pune"},
    "jaipur": {"jaipur"},
    "chennai": {"chennai", "madras"},
    "kolkata": {"kolkata", "calcutta"},
    "remote": {"remote", "work from home", "wfh", "anywhere", "work-from-home", "fully remote"},
}

WEIGHTS = {"keyword": 0.40, "skills": 0.25, "experience": 0.20, "location": 0.15}
RANK_MATCH_WEIGHT = 0.75
RANK_RECENCY_WEIGHT = 0.25


def canonicalize(text: str) -> str:
    t = " " + (text or "").lower() + " "
    t = t.replace("/", " ").replace("-", " ")
    t = re.sub(r"[^a-z0-9+# ]+", " ", t)
    t = re.sub(r"\s+", " ", t)
    for long, short in sorted(SYNONYMS.items(), key=lambda kv: -len(kv[0])):
        t = t.replace(" " + long.replace("-", " ") + " ", " " + short + " ")
    return t.strip()


def tokens(text: str, drop_stopwords: bool = True) -> set[str]:
    toks = set(canonicalize(text).split())
    if drop_stopwords:
        toks -= STOPWORDS
    return toks


def _job_text(job: dict) -> tuple[set[str], set[str], set[str]]:
    title = tokens(job.get("title", ""))
    skills = set()
    for s in job.get("skills") or []:
        skills |= tokens(s)
    desc = tokens(job.get("description", ""))
    return title, skills, desc


def keyword_score(job: dict, keywords: Iterable[str]) -> float:
    """How well the job title (mainly) and skills/description match the query."""
    title, skills, desc = _job_text(job)
    best = 0.0
    for kw in keywords or []:
        q = tokens(kw)
        if not q:
            # query consisted only of role words like "Engineer"
            q = tokens(kw, drop_stopwords=False)
            if not q:
                continue
        in_title = len(q & title) / len(q)
        in_other = len(q & (skills | desc)) / len(q)
        score = min(1.0, in_title + 0.5 * max(0.0, in_other - in_title))
        best = max(best, score)
    return round(best, 4)


def skill_score(job: dict, profile_skills: Iterable[str]) -> float:
    """Overlap between the profile's skills and the job's title/skills/description."""
    profile_skills = [s for s in (profile_skills or []) if s]
    if not profile_skills:
        return 0.5
    title, skills, desc = _job_text(job)
    job_toks = title | skills | desc
    matched = 0
    for s in profile_skills:
        st = tokens(s, drop_stopwords=False)
        if st and st <= job_toks:
            matched += 1
    # 3+ matching profile skills is a strong signal; scale up to that.
    return round(min(1.0, matched / 3.0), 4)


def experience_score(job: dict, experience_years: int | None) -> float:
    if experience_years is None or experience_years < 0:
        return 0.6
    lo, hi = int(job.get("exp_min", -1)), int(job.get("exp_max", -1))
    if lo < 0 and hi < 0:
        return 0.6
    if lo < 0:
        lo = 0
    if hi < 0:
        hi = OPEN_ENDED
    y = experience_years
    if lo <= y <= hi:
        return 1.0
    if y < lo:                      # under-qualified: penalise steeply
        return round(max(0.0, 1.0 - 0.3 * (lo - y)), 4)
    return round(max(0.0, 1.0 - 0.15 * (y - hi)), 4)  # over-qualified: softer


def _location_terms(pref: str) -> set[str]:
    p = pref.strip().lower()
    return LOCATION_ALIASES.get(p, {p})


def location_score(job: dict, preferred_locations: Iterable[str]) -> float:
    loc = (job.get("location") or "").lower()
    prefs = [p for p in (preferred_locations or []) if p]
    if not prefs:
        return 0.6
    if not loc or loc in ("india", "multiple locations", "various"):
        return 0.6
    loc_norm = " " + re.sub(r"[^a-z ]+", " ", loc) + " "
    for p in prefs:
        for term in _location_terms(p):
            if " " + term + " " in loc_norm:
                return 1.0
    if "hybrid" in loc:
        return 0.4
    return 0.2


def compute_match_score(job: dict, keywords: Iterable[str], experience_years: int | None,
                        profile_skills: Iterable[str], preferred_locations: Iterable[str]) -> float:
    parts = {
        "keyword": keyword_score(job, keywords),
        "skills": skill_score(job, profile_skills),
        "experience": experience_score(job, experience_years),
        "location": location_score(job, preferred_locations),
    }
    score = sum(WEIGHTS[k] * v for k, v in parts.items())
    return round(min(1.0, max(0.0, score)), 4)


def recency_score(posted_days_ago: int) -> float:
    try:
        d = int(posted_days_ago)
    except (TypeError, ValueError):
        d = -1
    if d < 0:
        return 0.4
    return round(max(0.05, 1.0 - d / 30.0), 4)


def compute_rank_score(match_score: float, posted_days_ago: int) -> float:
    return round(RANK_MATCH_WEIGHT * float(match_score)
                 + RANK_RECENCY_WEIGHT * recency_score(posted_days_ago), 4)


def experience_incompatible(job: dict, experience_years: int | None,
                            max_under: int = 2, max_over: int = 4) -> bool:
    """Clearly out of range: needs > years+2, or caps at < years-4."""
    if experience_years is None or experience_years < 0:
        return False
    lo, hi = int(job.get("exp_min", -1)), int(job.get("exp_max", -1))
    if lo >= 0 and lo > experience_years + max_under:
        return True
    if 0 <= hi < OPEN_ENDED and hi < experience_years - max_over:
        return True
    return False
