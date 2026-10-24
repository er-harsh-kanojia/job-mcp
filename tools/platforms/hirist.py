"""Hirist (hirist.tech) adapter.

Hirist is India's leading niche tech job portal.
  * Search navigates to Hirist's search page (e.g. /search?query=<skills>&loc=<location>)
    or keyword directory, extracting jobs from the client-side state
    (window.__PRELOADED_STATE__) or DOM cards.
  * Interactive login opens the headed browser to let the user authenticate once.
    Cookies / session tokens are persisted in .sessions/hirist.
  * Apply walks the job page and clicks "Apply" / "Quick Apply". Dry runs never click
    the final submission button.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from urllib.parse import quote_plus, urlsplit

from ..browser import (cookie_names, first_visible, human_pause,
                       human_scroll, safe_inner_text, wait_for_human_challenge)
from ..normalize import (coerce_int, parse_experience, parse_posted_days,
                         split_skills, strip_html)
from .base import APPLIED, DRY_RUN, FAILED, SKIPPED, PlatformAdapter, result

BASE = "https://www.hirist.tech"
PAGE_SIZE = 25

SUCCESS_RE = re.compile(
    r"\bapplied\b|application (sent|submitted|received)|successfully applied|your application has been sent",
    re.I
)
ALREADY_APPLIED_RE = re.compile(
    r"already applied|applied earlier|you have already applied",
    re.I
)

APPLY_BUTTONS = [
    "button:has-text('Quick Apply')",
    "button:has-text('Easy Apply')",
    "button:has-text('Apply')",
    "button[data-test-id*='apply' i]",
    "button[class*='apply' i]",
    "a:has-text('Quick Apply')",
    "a:has-text('Apply now')",
    "a:has-text('Apply')",
]

_PRELOADED_JS = """() => {
  try {
    const s = window.__PRELOADED_STATE__;
    if (s && s.feed && Array.isArray(s.feed.jobFeed) && s.feed.jobFeed.length) {
      return s.feed.jobFeed;
    }
    if (s && s.feed && s.feed.selectedJobs && Array.isArray(s.feed.selectedJobs) && s.feed.selectedJobs.length) {
      return s.feed.selectedJobs;
    }
    return null;
  } catch (e) { return null; }
}"""

_DOM_JS = r"""() => Array.from(document.querySelectorAll(
  'div[data-test-id*="job-card"], div[class*="jobCard"], div[class*="job-card"], div.feed-item, div.job-tuple, a[href*="-job-"], div[class*="jobContainer"]'
)).map(c => {
  const a = c.tagName === 'A' ? c : c.querySelector('a[href*="-job"], a[href*="/j/"], a[href*="/job/"], a');
  const t = (s) => { const e = c.querySelector(s); return e ? e.innerText.trim() : ''; };
  const text = c.innerText || '';
  return {
    url: a ? a.href : '',
    title: t('h2, h3, [class*="jobTitle"], [class*="title"], strong') || (a ? a.innerText.split('\n')[0].trim() : ''),
    company: t('[class*="company"], [class*="employer"], span.comp-name'),
    location: t('[class*="location"], [class*="loc"], span.loc'),
    exp: t('[class*="experience"], [class*="exp"]'),
    salary: t('[class*="salary"], [class*="ctc"], span.sal'),
    skills: Array.from(c.querySelectorAll('[class*="skill"], [class*="tag"], [class*="chip"]')).map(s => s.innerText.trim()).filter(Boolean),
    snippet: t('p, [class*="desc"], [class*="snippet"]'),
    posted: t('[class*="posted"], [class*="date"], span.time'),
    easy: /easy apply|quick apply|apply/i.test(text),
  };
}).filter(j => j.url && j.title)"""


def build_search_url(keywords: list[str], location: str = "") -> str:
    q = " ".join(k.strip() for k in keywords if k.strip())
    loc = (location or "").strip()
    url = f"{BASE}/search?query={quote_plus(q)}"
    if loc and loc.lower() != "india":
        url += f"&loc={quote_plus(loc)}"
    return url


def parse_feed_item(item: dict) -> dict | None:
    """Normalise an item from window.__PRELOADED_STATE__.feed.jobFeed."""
    if not isinstance(item, dict):
        return None
    jid = str(item.get("id") or item.get("jobId") or item.get("job_id") or "")
    title = str(item.get("title") or item.get("jobTitle") or "").strip()
    if not title:
        return None

    comp = item.get("companyName") or item.get("recruiterCompanyName")
    if not comp:
        comp_obj = item.get("company")
        if isinstance(comp_obj, dict):
            comp = comp_obj.get("name") or comp_obj.get("companyName")
        elif isinstance(comp_obj, str):
            comp = comp_obj
    comp = str(comp or "Unknown").strip()

    locs = item.get("locations") or item.get("location") or []
    if isinstance(locs, list):
        location = ", ".join(str(x) for x in locs if x)
    else:
        location = str(locs or "").strip()

    sal = item.get("salary") or item.get("ctc")
    if not sal:
        min_s = item.get("minSalary")
        max_s = item.get("maxSalary")
        if min_s is not None and max_s is not None:
            sal = f"{min_s}–{max_s} LPA"
        elif min_s is not None:
            sal = f"{min_s}+ LPA"
        else:
            sal = "Not disclosed"

    url = item.get("jobUrl") or item.get("url") or item.get("applyUrl") or ""
    if url and not url.startswith("http"):
        url = f"{BASE.rstrip('/')}/{url.lstrip('/')}"
    elif not url and jid:
        slug = item.get("slug") or f"job-{jid}"
        url = f"{BASE}/j/{slug}.html"

    skills = item.get("skills") or item.get("tags") or item.get("keywords") or []
    if isinstance(skills, str):
        skills = split_skills(skills)
    elif isinstance(skills, list):
        skills = [str(s).strip() for s in skills if s]

    exp_min = coerce_int(item.get("minExp") or item.get("expMin") or item.get("workex_min"), -1)
    exp_max = coerce_int(item.get("maxExp") or item.get("expMax") or item.get("workex_max"), -1)

    return {
        "platform": "hirist",
        "job_id": jid,
        "title": title,
        "company": comp,
        "location": location,
        "salary": sal,
        "apply_url": url,
        "description": strip_html(item.get("description") or item.get("jobDescription") or ""),
        "skills": skills,
        "exp_min": exp_min,
        "exp_max": exp_max,
        "posted_days_ago": parse_posted_days(item.get("postedDate") or item.get("createdDate") or -1),
        "easy_apply": True,
    }


def parse_dom_item(d: dict) -> dict | None:
    url = d.get("url") or ""
    title = d.get("title") or ""
    if not url or not title:
        return None
    m = re.search(r"[-/]([0-9a-zA-Z]+)(?:\.html)?(?:[?#]|$)", url)
    jid = m.group(1) if m else ""
    emin, emax = parse_experience(d.get("exp") or "")

    return {
        "platform": "hirist",
        "job_id": jid,
        "title": title,
        "company": d.get("company") or "Unknown",
        "location": d.get("location") or "",
        "salary": d.get("salary") or "Not disclosed",
        "apply_url": url,
        "description": strip_html(d.get("snippet") or ""),
        "skills": d.get("skills") or [],
        "exp_min": emin,
        "exp_max": emax,
        "posted_days_ago": parse_posted_days(d.get("posted") or -1),
        "easy_apply": bool(d.get("easy", True)),
    }


class HiristAdapter(PlatformAdapter):
    name = "hirist"
    login_url = f"{BASE}/login"
    home_url = f"{BASE}/"
    login_email_selectors = [
        "input[name='email']",
        "input[type='email']",
        "input[placeholder*='email' i]",
        "input[placeholder*='mobile' i]",
    ]
    search_timeout = 90.0
    search_requires_login = False

    async def is_logged_in(self, page) -> bool:
        """Check login state using cookies and visible user profile selectors."""
        try:
            names = await cookie_names(page)
            if any(k in names for k in ("auth_token", "jwt", "user_id", "sessionid", "token", "logged_in", "user_token")):
                return True
        except Exception as exc:
            self.log.debug("hirist: cookie check failed: %s", exc)

        try:
            profile_btn = await first_visible(page, [
                ".user-avatar",
                "[data-test-id*='profile' i]",
                "a[href*='/candidate/' i]",
                "a[href*='/profile' i]",
                "button:has-text('My Profile')",
                "a:has-text('Profile')",
                "a:has-text('Logout')",
                "button:has-text('Logout')",
            ])
            return profile_btn is not None
        except Exception:
            return False

    async def search(self, keywords: list[str], location: str, experience_years: int,
                     limit: int = 40) -> list[dict]:
        """Search jobs on Hirist by loading the search results page."""
        url = build_search_url(keywords, location)
        self.log.info("hirist: searching via %s", url)
        out: list[dict] = []

        async with self.browser() as ctx:
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await wait_for_human_challenge(page, self.name)
                await human_pause(1.0, 2.0)

                # 1. Try extracting from window.__PRELOADED_STATE__
                try:
                    feed_items = await page.evaluate(_PRELOADED_JS)
                    if feed_items and isinstance(feed_items, list):
                        for it in feed_items:
                            rec = parse_feed_item(it)
                            if rec and rec["apply_url"]:
                                out.append(rec)
                                if len(out) >= limit:
                                    break
                except Exception as exc:
                    self.log.debug("hirist: preloaded state eval failed: %s", exc)

                # 2. Fallback to DOM parsing if state was empty
                if not out:
                    await human_scroll(page, steps=3, distance=500)
                    await asyncio.sleep(1.0)
                    cards = await page.evaluate(_DOM_JS)
                    if cards and isinstance(cards, list):
                        for c in cards:
                            rec = parse_dom_item(c)
                            if rec and rec["apply_url"]:
                                out.append(rec)
                                if len(out) >= limit:
                                    break
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

        self.log.info("hirist: found %d raw jobs", len(out))
        return out

    async def apply(self, job: dict, profile: dict, dry_run: bool = True) -> dict:
        """Apply to a job on Hirist."""
        url = job.get("apply_url") or ""
        if not url:
            return result(FAILED, "Missing apply_url")

        async with self.browser() as ctx:
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await wait_for_human_challenge(page, self.name)
                await human_pause(1.0, 2.0)

                # Check if already applied
                body_text = await page.inner_text("body")
                if ALREADY_APPLIED_RE.search(body_text):
                    return result(SKIPPED, "Already applied on Hirist")

                btn = await first_visible(page, APPLY_BUTTONS)
                if not btn:
                    return result(FAILED, "Apply button not found on Hirist job page")

                btn_text = (await safe_inner_text(btn)).strip()
                if ALREADY_APPLIED_RE.search(btn_text):
                    return result(SKIPPED, "Already applied on Hirist")

                if dry_run:
                    return result(DRY_RUN, f"Dry run: would click '{btn_text}' on Hirist for {job.get('title')}")

                # Live apply
                await btn.click()
                await human_pause(1.5, 3.0)

                # Check for confirm modal if any
                confirm_btn = await first_visible(page, [
                    "button:has-text('Confirm')",
                    "button:has-text('Submit')",
                    "button:has-text('Send Application')",
                ])
                if confirm_btn:
                    await confirm_btn.click()
                    await human_pause(1.5, 3.0)

                new_body = await page.inner_text("body")
                if SUCCESS_RE.search(new_body) or ALREADY_APPLIED_RE.search(new_body):
                    return result(APPLIED, "Application submitted on Hirist")

                return result(APPLIED, "Apply clicked on Hirist")
            except Exception as exc:
                self.log.warning("hirist: apply failed: %s", exc)
                return result(FAILED, f"Apply error on Hirist: {exc}")
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
