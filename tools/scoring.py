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

# Match score = weighted parts, each 0-1. Tuned so only strong fits score near 1:
# a title squarely in AI/ML, most of the job's listed skills on your profile,
# experience in range, preferred location.
WEIGHTS = {"title": 0.40, "skills": 0.30, "experience": 0.20, "location": 0.10}
RANK_MATCH_WEIGHT = 0.75
RANK_RECENCY_WEIGHT = 0.25

# Title tokens (after canonicalize) that mark an AI/ML role.
CORE_ROLE = {"ai", "ml", "genai", "llm", "nlp", "dl", "cv", "rag", "mlops", "datascience", "agentic",
             "generative", "langchain", "pytorch", "tensorflow", "llmops", "ai/ml", "aiml"}
# Title words that point away from an AI/ML engineering role.
OFF_TARGET = {"java", "frontend", "android", "ios", "flutter", "react", "angular", "php", "dotnet", "net",
              "sales", "marketing", "support", "qa", "tester", "testing", "test", "manual", "sap", "oracle",
              "salesforce", "servicenow", "recruiter", "hr", "intern", "internship", "trainee", "fresher",
              "teacher", "faculty", "trainer", "tutor", "content", "writer", "annotator", "annotation",
              "accountant", "embedded", "hardware", "mechanical", "civil", "electrical", "mainframe",
              "sre", "observability", "network", "tableau", "powerbi", "bdm", "presales", "pre"}
# Titles usually too senior for a mid-level profile (penalised, not excluded).
SENIOR = {"principal", "staff", "architect", "head", "director", "vp", "manager", "chief"}

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


def title_score(job: dict, keywords: Iterable[str]) -> float:
    """How squarely the title is an AI/ML role and how well it matches the search keywords."""
    raw_title = tokens(job.get("title", ""), drop_stopwords=False)
    title = raw_title - STOPWORDS
    core = title & CORE_ROLE
    cover = 0.0
    for kw in keywords or []:
        q = tokens(kw) or tokens(kw, drop_stopwords=False)
        if q:
            cover = max(cover, len(q & title) / len(q))
    if core:
        score = 0.55 + 0.25 * min(1.0, len(core) / 2) + 0.20 * cover
    else:
        score = 0.30 * cover  # no AI/ML word in the title at all
    if raw_title & OFF_TARGET:
        score *= 0.5
    if raw_title & SENIOR:
        score *= 0.85
    return round(min(1.0, score), 4)


def _profile_vocab(profile_skills: Iterable[str]) -> set[str]:
    vocab: set[str] = set()
    for s in profile_skills or []:
        vocab |= tokens(s, drop_stopwords=False)
    return vocab


def skill_score(job: dict, profile_skills: Iterable[str]) -> float:
    """Share of the job's listed skills that are on your profile (or, without a skills list,
    how many of your skills the title/description mention)."""
    vocab = _profile_vocab(profile_skills)
    if not vocab:
        return 0.5
    listed = [tokens(s, drop_stopwords=False) - STOPWORDS for s in job.get("skills") or []]
    listed = [t for t in listed if t]
    if len(listed) >= 3:
        have = sum(1 for t in listed if t & vocab)
        return round(0.15 + 0.85 * have / len(listed), 4)
    title, skills, desc = _job_text(job)
    mentioned = len(vocab & (title | skills | desc))
    return round(min(1.0, 0.25 + 0.12 * mentioned), 4)


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
        # a very wide band ("0-15 yrs") says little about fit
        return 1.0 if hi - lo <= 6 else 0.85
    if y < lo:                      # under-qualified: penalise steeply
        return round(max(0.0, 1.0 - 0.3 * (lo - y)), 4)
    return round(max(0.0, 1.0 - 0.15 * (y - hi)), 4)  # over-qualified: softer


def keyword_score(job: dict, keywords: Iterable[str]) -> float:
    """Kept for callers of the old API: the title part of the match score."""
    return title_score(job, keywords)


def compute_match_score(job: dict, keywords: Iterable[str], experience_years: int | None,
                        profile_skills: Iterable[str], preferred_locations: Iterable[str]) -> float:
    parts = {
        "title": title_score(job, keywords),
        "skills": skill_score(job, profile_skills),
        "experience": experience_score(job, experience_years),
        "location": location_score(job, preferred_locations),
    }
    score = sum(WEIGHTS[k] * v for k, v in parts.items())
    if parts["title"] < 0.2:
        # not an AI/ML role at all: experience and location alone mustn't carry it
        score = min(score, 0.2)
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
