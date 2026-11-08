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
  '.joblist-card-v2, div[class*="joblist-card"], div[data-test-id*="job-card"], div[class*="jobCard"], div[class*="job-card"], div.feed-item, div.job-tuple'
)).map(c => {
  const a = c.querySelector('a[href*="/j/"], a[href*="-job"], a[href*="/job/"]') || (c.tagName === 'A' ? c : c.closest('a') || c.querySelector('a'));
  
  let title = '';
  const titleEl = c.querySelector('[data-testid="job_title"], h2, h3, [class*="jobTitle"], [class*="title"]');
  if (titleEl) {
    const clone = titleEl.cloneNode(true);
    const saveIcon = clone.querySelector('.save-icon, [aria-label*="Save"]');
    if (saveIcon) saveIcon.remove();
    title = clone.innerText.trim();
  } else if (a) {
    title = a.innerText.split('\n')[0].trim();
  }

  const compEl = c.querySelector('[class*="company"], [class*="employer"], span.comp-name');
  const company = compEl ? compEl.innerText.trim() : '';

  const expEl = c.querySelector('[data-testid="job_experience"], [class*="experience"], [class*="exp"]');
  const exp = expEl ? expEl.innerText.trim() : '';

  const locEl = c.querySelector('[data-testid="job_location"], [class*="location"], [class*="loc"], span.loc');
  const location = locEl ? locEl.innerText.trim() : '';

  const salEl = c.querySelector('[data-testid="job_salary"], [class*="salary"], [class*="ctc"], span.sal');
  const salary = salEl ? salEl.innerText.trim() : '';

  const skills = Array.from(c.querySelectorAll('[data-testid^="job_tag_"], [class*="skill"], [class*="tag"], [class*="chip"]'))
    .map(s => s.innerText.trim())
    .filter(Boolean);

  const postedEl = c.querySelector('[data-testid="date_posted"], [data-testid="date_posted_mobile"], [class*="posted"], [class*="date"], span.time');
  const posted = postedEl ? postedEl.innerText.trim() : '';

  const snipEl = c.querySelector('p:not([data-testid="job_title"]):not([data-testid="job_location"]), [class*="desc"], [class*="snippet"]');
  const snippet = snipEl ? snipEl.innerText.trim() : '';

  return {
    url: a ? a.href : '',
    title: title,
    company: company,
    location: location,
    exp: exp,
    salary: salary,
    skills: skills,
    snippet: snippet,
    posted: posted,
    easy: true,
  };
}).filter(j => j.url && j.title)"""


def build_search_url(keywords: list[str], location: str = "", experience_years: int = -1, page: int = 1) -> str:
    q = " ".join(k.strip() for k in keywords if k.strip())
    loc = (location or "").strip()
    if q:
        url = f"{BASE}/search/{quote_plus(q)}"
    else:
        url = f"{BASE}/search"

    params: list[str] = []
    if loc and loc.lower() != "india":
        params.append(f"loc={quote_plus(loc)}")
    if experience_years is not None and experience_years >= 0:
        params.append(f"minexp={max(0, experience_years - 2)}")
        params.append(f"maxexp={experience_years + 2}")
    if page > 1:
        params.append(f"page={page}")

    if params:
        url += f"?{'&'.join(params)}"
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


ROLE_PREFIXES = {
    "developer", "engineer", "lead", "architect", "senior", "junior", "intern", "manager",
    "consultant", "analyst", "specialist", "director", "head", "associate", "programmer",
    "qa", "sdet", "devops", "sre", "data", "software", "backend", "frontend", "fullstack"
}


def parse_dom_item(d: dict) -> dict | None:
    url = (d.get("url") or "").strip()
    title = (d.get("title") or "").strip()
    if not url or not title:
        return None

    clean_url = url.split("?")[0].split("#")[0]
    m = re.search(r"-(\d+)(?:[?#]|$)", url)
    if not m:
        m = re.search(r"[-/]([0-9a-zA-Z]+)(?:\.html)?(?:[?#]|$)", url)
    jid = m.group(1) if m else ""

    emin, emax = parse_experience(d.get("exp") or "")

    company = (d.get("company") or "").strip()
    if not company or company.lower() == "unknown":
        if " - " in title:
            parts = [p.strip() for p in title.split(" - ")]
            first_words = {w.lower() for w in parts[0].split()}
            if not (first_words & ROLE_PREFIXES):
                company = parts[0]
                if len(parts) > 1:
                    title = " - ".join(parts[1:])
            else:
                company = "Hirist Recruiter"
        else:
            company = "Hirist Recruiter"

    return {
        "platform": "hirist",
        "job_id": jid,
        "title": title,
        "company": company,
        "location": d.get("location") or "",
        "salary": d.get("salary") or "Not disclosed",
        "apply_url": clean_url,
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
        """Check login state: the seeker session cookie first, then the page header.

        Logged-in visitors get ``hirist_seeker_enc`` and are sent from the home page to
        /jobfeed; logged-out ones get neither. The header is rendered by React after the
        HTML loads, so the selector check waits a few seconds for it.
        """
        if "/login" in (page.url or ""):
            return False
        names = await cookie_names(page.context, BASE)
        if "hirist_seeker_enc" in names:
            return True
        if urlsplit(page.url or "").path.startswith("/jobfeed"):
            return True

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
            ], timeout_ms=6_000)
            return profile_btn is not None
        except Exception:
            return False

    async def search(self, keywords: list[str], location: str, experience_years: int,
                     limit: int = 40) -> list[dict]:
        """Search jobs on Hirist by loading the search results page."""
        self.log.info("hirist: searching for %s (loc=%s, exp=%s, limit=%d)",
                      keywords, location, experience_years, limit)
        out: list[dict] = []
        seen_urls: set[str] = set()

        max_pages = max(1, (limit + 19) // 20)
        max_pages = min(max_pages, 3)

        async with self.browser() as ctx:
            page = await ctx.new_page()
            try:
                for pno in range(1, max_pages + 1):
                    url = build_search_url(keywords, location, experience_years, page=pno)
                    self.log.info("hirist: navigating to page %d: %s", pno, url)
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    except Exception as e:
                        self.log.warning("hirist: goto %s failed: %s", url, e)
                        break

                    await wait_for_human_challenge(page, self.name)
                    try:
                        await page.wait_for_selector('.joblist-card-v2, a[href*="/j/"]', timeout=8_000)
                    except Exception:
                        pass
                    await human_pause(0.5, 1.2)

                    # 1. Try extracting from window.__PRELOADED_STATE__ if available
                    try:
                        feed_items = await page.evaluate(_PRELOADED_JS)
                        if feed_items and isinstance(feed_items, list):
                            for it in feed_items:
                                rec = parse_feed_item(it)
                                if rec and rec["apply_url"] and rec["apply_url"] not in seen_urls:
                                    seen_urls.add(rec["apply_url"])
                                    out.append(rec)
                                    if len(out) >= limit:
                                        break
                    except Exception as exc:
                        self.log.debug("hirist: preloaded state eval failed: %s", exc)

                    # 2. Extract from DOM cards
                    if len(out) < limit:
                        cards = await page.evaluate(_DOM_JS)
                        if cards and isinstance(cards, list):
                            new_in_page = 0
                            for c in cards:
                                rec = parse_dom_item(c)
                                if rec and rec["apply_url"] and rec["apply_url"] not in seen_urls:
                                    seen_urls.add(rec["apply_url"])
                                    out.append(rec)
                                    new_in_page += 1
                                    if len(out) >= limit:
                                        break
                            if new_in_page == 0:
                                break

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
