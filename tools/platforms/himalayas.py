"""Himalayas (himalayas.app): remote jobs, via its public JSON search API.

``GET https://himalayas.app/jobs/api/search?q=<keyword>&page=<n>&country=<Country>``
returns 20 jobs a page. ``country`` keeps jobs you can take from that country
(including worldwide ones); ``worldwide=true`` keeps only jobs open everywhere.
No login. Jobs are applied to on Himalayas / the company's site ("Apply on site").
"""

from __future__ import annotations

import math
import time
from typing import Any

from ..normalize import days_since_epoch_ms
from .public import PublicBoardAdapter, wanted_country

API = "https://himalayas.app/jobs/api/search"
PAGE_SIZE = 20
MAX_PAGES = 5

# Himalayas seniority -> (exp_min, exp_max) in years
SENIORITY_YEARS: list[tuple[str, tuple[int, int]]] = [
    ("intern", (0, 1)),
    ("entry", (0, 2)),
    ("junior", (0, 2)),
    ("mid", (2, 5)),
    ("senior", (5, 99)),
    ("staff", (8, 99)),
    ("principal", (10, 99)),
    ("lead", (7, 99)),
    ("manager", (7, 99)),
    ("director", (10, 99)),
    ("executive", (12, 99)),
]


def experience_from_seniority(levels: list[str] | None) -> tuple[int, int]:
    """Widest year range covering all listed seniority levels; (-1, -1) when unknown."""
    lo, hi = None, None
    for level in levels or []:
        key = (level or "").lower()
        for word, (a, b) in SENIORITY_YEARS:
            if word in key:
                lo = a if lo is None else min(lo, a)
                hi = b if hi is None else max(hi, b)
                break
    return (lo, hi) if lo is not None else (-1, -1)


def _money(n: Any) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return ""
    return f"{v / 1000:.0f}k" if v >= 1000 else f"{v:.0f}"


def format_salary(lo: Any, hi: Any, currency: str | None, period: str | None) -> str:
    a, b = _money(lo), _money(hi)
    if not a and not b:
        return ""
    amount = f"{a}–{b}" if a and b and a != b else (a or b)
    unit = {"annual": "/ yr", "yearly": "/ yr", "monthly": "/ mo", "hourly": "/ hr"}.get((period or "").lower(), "")
    return " ".join(x for x in (currency or "", amount, unit) if x)


def format_location(restrictions: list[str] | None) -> str:
    places = [p for p in (restrictions or []) if p]
    if not places:
        return "Remote (worldwide)"
    if len(places) <= 3:
        return "Remote · " + ", ".join(places)
    return f"Remote · {', '.join(places[:2])} +{len(places) - 2} more"


def parse_job(item: dict, now: float | None = None) -> dict | None:
    url = item.get("guid") or item.get("applicationLink")
    if not url or not item.get("title"):
        return None
    exp_min, exp_max = experience_from_seniority(item.get("seniority"))
    pub = item.get("pubDate")
    posted = days_since_epoch_ms(float(pub) * 1000, now) if isinstance(pub, (int, float)) else -1
    return {
        "job_id": url,
        "title": item.get("title"),
        "company": item.get("companyName"),
        "location": format_location(item.get("locationRestrictions")),
        "salary": format_salary(item.get("minSalary"), item.get("maxSalary"),
                                item.get("currency"), item.get("salaryPeriod")),
        "description": item.get("description") or item.get("excerpt") or "",
        # Himalayas "categories" are role names, not skills: scoring reads the description instead.
        "skills": [],
        "exp_min": exp_min,
        "exp_max": exp_max,
        "posted_days_ago": posted,
        "apply_url": url,
        "easy_apply": False,
    }


class HimalayasAdapter(PublicBoardAdapter):
    name = "himalayas"
    home_url = "https://himalayas.app/"

    @property
    def display_name(self) -> str:
        return "Himalayas"

    async def search(self, keywords: list[str], location: str, experience_years: int,
                     limit: int = 40) -> list[dict]:
        country = wanted_country(location)
        where: dict[str, str] = {"country": country} if country else {"worldwide": "true"}
        out: list[dict] = []
        seen: set[str] = set()
        now = time.time()
        pages = min(MAX_PAGES, max(1, math.ceil(limit / PAGE_SIZE)))
        async with self.http() as client:
            for kw in keywords:
                for page in range(1, pages + 1):
                    resp = await client.get(API, params={"q": kw, "page": page, **where})
                    if resp.status_code != 200:
                        self.log.warning("himalayas: HTTP %s for %r page %d", resp.status_code, kw, page)
                        break
                    data = resp.json()
                    items = data.get("jobs") or []
                    if page == 1 and not items and "country" in where:
                        # Unknown country name: fall back to jobs open worldwide.
                        where = {"worldwide": "true"}
                        resp = await client.get(API, params={"q": kw, "page": 1, **where})
                        items = resp.json().get("jobs") or [] if resp.status_code == 200 else []
                    for it in items:
                        job = parse_job(it, now)
                        if job and job["apply_url"] not in seen:
                            seen.add(job["apply_url"])
                            out.append(job)
                    if len(items) < PAGE_SIZE or len(out) >= limit * len(keywords):
                        break
        self.log.info("himalayas: %d jobs for %s (%s)", len(out), keywords, country or "worldwide")
        return out
