"""YC job board (ycombinator.com/jobs): jobs at Y Combinator startups.

Each listing page (e.g. /jobs/role/software-engineer/india) embeds its postings as
JSON in the ``data-page`` attribute, so no login or browser is needed. The public
board shows a few dozen postings per page; the full board (Work at a Startup) needs
a YC account. Applying happens on YC's site ("Apply on site").

Postings marked "US citizen/visa only" are dropped unless they are in your location,
since you can't take them from elsewhere; "Will sponsor" marks a job as visa-sponsored.
"""

from __future__ import annotations

import html
import json
import re

from ..normalize import parse_experience, parse_posted_days
from .public import PublicBoardAdapter, wanted_country

BASE = "https://www.ycombinator.com"
# Listing pages to read (deduped by posting id). Location pages are added per search.
ROLE_PAGES = ["/jobs/role/software-engineer", "/jobs/role/software-engineer/remote", "/jobs/role/science"]
LOCATION_PAGES = {"india": "/jobs/role/software-engineer/india"}
DATA_PAGE_RE = re.compile(r'data-page="([^"]+)"')

US_ONLY = "us citizen/visa only"
SPONSORS = "will sponsor"

# Words that don't tell roles apart ("Senior ML Engineer" is about "ml").
GENERIC = {"engineer", "engineers", "developer", "developers", "software", "sde", "senior", "junior", "lead", "staff",
           "principal", "sr", "jr", "the", "and", "of", "for", "jobs", "job", "role", "remote"}
ALIASES = {
    "ml": ["machine learning", "ml"],
    "ai": ["ai", "artificial intelligence", "machine learning", "llm"],
    "genai": ["genai", "generative", "llm", "ai"],
    "llm": ["llm", "language model", "genai", "ai"],
    "nlp": ["nlp", "language"],
    "dl": ["deep learning"],
}


def keyword_terms(keywords: list[str]) -> list[str]:
    """Distinctive search terms, e.g. ["AI/ML Engineer"] -> ["ai", "artificial intelligence", ..., "ml"]."""
    terms: list[str] = []
    for kw in keywords:
        words = [w for w in re.split(r"[^a-z0-9+#.]+", (kw or "").lower()) if w and w not in GENERIC]
        text = " ".join(words)
        if "machine learning" in text or "deep learning" in text:
            terms.append("machine learning" if "machine" in text else "deep learning")
        for w in words:
            terms.extend(ALIASES.get(w, [w]))
    return list(dict.fromkeys(terms))


def matches_terms(text: str, terms: list[str]) -> bool:
    if not terms:
        return True
    low = " " + re.sub(r"[^a-z0-9+#.]+", " ", text.lower()) + " "
    return any(f" {t} " in low for t in terms)


def parse_listing(page_html: str) -> list[dict]:
    m = DATA_PAGE_RE.search(page_html or "")
    if not m:
        return []
    try:
        data = json.loads(html.unescape(m.group(1)))
    except ValueError:
        return []
    return list((data.get("props") or {}).get("jobPostings") or [])


def parse_posting(p: dict) -> dict | None:
    if not p.get("url") or not p.get("title"):
        return None
    exp_text = p.get("minExperience") or ""
    exp_min, exp_max = parse_experience(exp_text)
    if exp_min < 0 and "any" in exp_text.lower():
        exp_min, exp_max = 0, 99
    skills = [s if isinstance(s, str) else (s or {}).get("name", "") for s in p.get("skills") or []]
    about = " · ".join(x for x in (p.get("companyOneLiner"), p.get("prettyRole"), p.get("roleSpecificType"),
                                   p.get("type"), f"Visa: {p['visa']}" if p.get("visa") else "",
                                   f"YC {p['companyBatchName']}" if p.get("companyBatchName") else "") if x)
    return {
        "job_id": str(p.get("id") or p["url"]),
        "title": p.get("title"),
        "company": p.get("companyName"),
        "location": p.get("location") or "",
        "salary": " + ".join(x for x in (p.get("salaryRange"), p.get("equityRange") and f"{p['equityRange']} equity") if x),
        "description": about,
        "skills": [s for s in skills if s],
        "exp_min": exp_min,
        "exp_max": exp_max,
        "posted_days_ago": parse_posted_days(p.get("createdAt")),
        "apply_url": BASE + p["url"],
        "easy_apply": False,
        "visa_sponsored": SPONSORS in (p.get("visa") or "").lower(),
        "_visa": p.get("visa") or "",
        "_role_text": " ".join([p.get("title") or "", p.get("roleSpecificType") or "", " ".join(skills)]),
    }


def can_take(job: dict, country: str | None) -> bool:
    """Drop US-only postings unless they are in the country you're searching in."""
    if US_ONLY not in job.get("_visa", "").lower():
        return True
    loc = (job.get("location") or "").lower()
    if country is None:
        return False
    c = country.lower()
    if c == "india":
        return "india" in loc or re.search(r"\bin\b", loc) is not None
    return c in loc or (c in ("united states", "usa", "us") and ("us" in loc.split() or ", ca" in loc))


class YCombinatorAdapter(PublicBoardAdapter):
    name = "ycombinator"
    home_url = f"{BASE}/jobs"

    @property
    def display_name(self) -> str:
        return "YC Jobs"

    async def search(self, keywords: list[str], location: str, experience_years: int,
                     limit: int = 40) -> list[dict]:
        country = wanted_country(location)
        pages = list(ROLE_PAGES)
        if country and country.lower() in LOCATION_PAGES:
            pages.insert(0, LOCATION_PAGES[country.lower()])
        terms = keyword_terms(keywords)
        out: list[dict] = []
        seen: set[str] = set()
        async with self.http() as client:
            for path in pages:
                resp = await client.get(BASE + path)
                if resp.status_code != 200:
                    self.log.warning("ycombinator: HTTP %s for %s", resp.status_code, path)
                    continue
                for p in parse_listing(resp.text):
                    job = parse_posting(p)
                    if not job or job["apply_url"] in seen:
                        continue
                    seen.add(job["apply_url"])
                    if not matches_terms(job["_role_text"], terms) or not can_take(job, country):
                        continue
                    for k in ("_visa", "_role_text"):
                        job.pop(k, None)
                    out.append(job)
        self.log.info("ycombinator: %d of %d postings match %s (%s)", len(out), len(seen), keywords,
                      country or "anywhere")
        return out[:max(limit, 1) * max(1, len(keywords))]
