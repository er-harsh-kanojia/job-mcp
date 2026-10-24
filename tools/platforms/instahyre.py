"""Instahyre adapter.

Search uses Instahyre's JSON API (verified Oct 2026):
  GET /api/v1/job_search/?skills=<text>&years=<n>&limit=35&offset=N
      -> {"meta": {...,"total_count"}, "objects": [{id, title, employer{company_name},
          locations "A,B", keywords[...], public_url}]}
      ``skills`` acts as a relevance search (one value), ``years`` filters by
      experience. Location is NOT filterable server-side (scored locally).
  GET /api/v1/employer_public_jobs/<id>
      -> {workex_min, workex_max, description (HTML), locations[], is_active, ...}
Both work without login; when a logged-in context is bound its cookies are used.

Apply: open the job page in the logged-in browser and click "Apply" / "Interested"
(``submitChoice``). The "apply to similar jobs in bulk" prompt is always declined.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from ..browser import cookie_names, first_visible, human_pause, human_scroll, safe_inner_text
from ..config import data_dir
from ..normalize import coerce_int, split_skills, strip_html
from .base import APPLIED, DRY_RUN, FAILED, SKIPPED, PlatformAdapter, result

log = logging.getLogger("job_mcp.instahyre")

BASE = "https://www.instahyre.com"
SEARCH_API = f"{BASE}/api/v1/job_search/"
DETAIL_API = f"{BASE}/api/v1/employer_public_jobs/"
PAGE_SIZE = 35

SUCCESS_RE = re.compile(r"\bapplied\b|application (sent|submitted)|shown interest|we.ll (let you know|notify)", re.I)
APPLY_SELECTORS = [
    "button[ng-click*='submitChoice']",
    "button:text-is('Apply')",
    "button:has-text('Apply now')",
    "button:text-is('Interested')",
]


async def _click_apply(page, btn) -> bool:
    """Click Instahyre's "Apply now". The button sits inside an <a>, which Playwright reports as
    intercepting the click, so a normal click times out; fall back to a coordinate click, then a
    DOM click (which still fires Angular's ng-click)."""
    for _ in range(20):  # ng-disabled="!jobDataLoaded": wait for the job data
        try:
            if await btn.is_enabled():
                break
        except Exception:
            break
        await asyncio.sleep(0.5)
    for how in ("normal", "force", "dom"):
        try:
            if how == "normal":
                await btn.click(timeout=4000)
            elif how == "force":
                await btn.click(force=True, timeout=4000)
            else:
                await btn.evaluate("e => e.click()")
            log.info("instahyre: clicked Apply (%s)", how)
            return True
        except Exception as exc:
            log.info("instahyre: %s click on Apply failed: %s", how, str(exc).splitlines()[0][:120])
    return False


async def _dump_debug(page, tag: str) -> None:
    """Save a screenshot and the HTML of the current page to data/debug/ for diagnosis."""
    try:
        out = data_dir() / "debug"
        out.mkdir(parents=True, exist_ok=True)
        stem = out / f"instahyre-{time.strftime('%Y%m%d-%H%M%S')}-{tag}"
        await page.screenshot(path=str(stem) + ".png", full_page=True)
        (stem.parent / (stem.name + ".html")).write_text(await page.content(), encoding="utf-8")
        log.warning("instahyre: saved debug capture %s.{png,html} (url %s)", stem, page.url)
    except Exception as exc:
        log.warning("instahyre: debug capture failed: %s", exc)


def parse_search_object(o: dict) -> dict | None:
    if not isinstance(o, dict) or not o.get("id") or not o.get("title"):
        return None
    emp = o.get("employer") or {}
    locs = o.get("locations") or ""
    if isinstance(locs, list):
        locs = ", ".join(map(str, locs))
    locs = ", ".join(x.strip() for x in str(locs).split(",") if x.strip())
    url = o.get("public_url") or f"{BASE}/job-{o['id']}/"
    return {
        "platform": "instahyre",
        "job_id": str(o["id"]),
        "title": o.get("title") or o.get("candidate_title") or "",
        "company": emp.get("company_name") or "",
        "location": locs,
        "salary": "",
        "apply_url": url,
        "description": strip_html(emp.get("instahyre_note") or "", max_len=600),
        "skills": split_skills(o.get("keywords") or []),
        "exp_min": -1,
        "exp_max": -1,
        "posted_days_ago": -1,
        "easy_apply": True,
    }


def merge_detail(job: dict, d: dict) -> dict | None:
    """Enrich a job with /employer_public_jobs/<id>; None if the job is inactive."""
    if not isinstance(d, dict):
        return job
    if d.get("is_active") is False:
        return None
    lo, hi = coerce_int(d.get("workex_min")), coerce_int(d.get("workex_max"))
    if lo >= 0:
        job["exp_min"] = lo
        job["exp_max"] = hi if hi >= 0 else 99
    if d.get("description"):
        job["description"] = strip_html(d["description"], max_len=1500)
    if d.get("locations") and isinstance(d["locations"], list):
        job["location"] = ", ".join(map(str, d["locations"]))
    if d.get("keywords"):
        job["skills"] = split_skills(d["keywords"])
    if d.get("hiring_company_name") and not job.get("company"):
        job["company"] = d["hiring_company_name"]
    return job


class InstahyreAdapter(PlatformAdapter):
    name = "instahyre"
    login_url = f"{BASE}/login/"
    home_url = f"{BASE}/candidate/opportunities/?matching=true"
    login_email_selectors = ["#email", "input[name='email']", "input[type='email']"]
    search_timeout = 75.0

    async def is_logged_in(self, page) -> bool:
        url = page.url or ""
        if "/login" in url or "/signup" in url:
            return False
        if "/candidate/" in url:
            return True
        names = await cookie_names(page.context, BASE)
        if "sessionid" not in names:
            return False
        return await first_visible(page, ["a[href*='logout']", "a[href*='/candidate/profile']",
                                          "a[href*='/candidate/opportunities']"]) is not None

    # ---------------------------------------------------------------- search
    async def _get_json(self, req, url: str, params: dict | None = None):
        resp = await req.get(url, params=params, timeout=30_000,
                             headers={"accept": "application/json"})
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status} from {url}")
        return await resp.json()

    async def _search_with(self, req, keywords, experience_years, limit) -> list[dict]:
        jobs: dict[str, dict] = {}
        per_kw = max(PAGE_SIZE, limit)
        for kw in keywords or [""]:
            offset = 0
            while offset < per_kw:
                params = {"limit": str(PAGE_SIZE), "offset": str(offset)}
                if kw.strip():
                    params["skills"] = kw.strip()
                if experience_years is not None and experience_years > 0:
                    params["years"] = str(int(experience_years))
                data = await self._get_json(req, SEARCH_API, params)
                objs = data.get("objects") or []
                for o in objs:
                    j = parse_search_object(o)
                    if j and j["job_id"] not in jobs:
                        jobs[j["job_id"]] = j
                offset += PAGE_SIZE
                total = coerce_int((data.get("meta") or {}).get("total_count"), 0)
                if len(objs) < PAGE_SIZE or offset >= total or len(jobs) >= limit:
                    break
                await asyncio.sleep(0.6)
        selected = list(jobs.values())[:limit]

        sem = asyncio.Semaphore(5)

        async def enrich(j):
            async with sem:
                try:
                    return merge_detail(j, await self._get_json(req, f"{DETAIL_API}{j['job_id']}"))
                except Exception as exc:
                    self.log.debug("instahyre: detail fetch failed for %s: %s", j["job_id"], exc)
                    return j
        enriched = await asyncio.gather(*(enrich(j) for j in selected))
        return [j for j in enriched if j]

    async def search(self, keywords, location, experience_years, limit=40):
        # No browser window is needed for the JSON API; reuse a bound context's
        # cookies if there is one, otherwise use a standalone request context.
        if self.context is not None:
            return await self._search_with(self.context.request, keywords, experience_years, limit)
        from playwright.async_api import async_playwright
        from ..browser import build_user_agent
        async with async_playwright() as pw:
            req = await pw.request.new_context(user_agent=build_user_agent("130"),
                                               extra_http_headers={"accept-language": "en-IN,en;q=0.9"})
            try:
                return await self._search_with(req, keywords, experience_years, limit)
            finally:
                await req.dispose()

    # ----------------------------------------------------------------- apply
    async def apply(self, job, profile, dry_run=True):
        async with self.browser() as ctx:
            page = await self.page()
            await page.goto(job["apply_url"], wait_until="domcontentloaded", timeout=45_000)
            await human_pause(2.0, 4.0)
            await human_scroll(page, 2)
            if not await self.is_logged_in(page):
                # job pages don't live under /candidate/, so double-check via cookies + DOM
                names = await cookie_names(ctx, BASE)
                if "sessionid" not in names:
                    return result(FAILED, "Not logged in to Instahyre. Run login (run.py option 1) first.")

            if await first_visible(page, ["button:text-is('Applied')", "button:has-text('Already applied')",
                                          "span:text-is('Applied')"]):
                return result(SKIPPED, "already applied (detected on site)")

            btn = await first_visible(page, APPLY_SELECTORS, timeout_ms=8000)
            if btn is None:
                body = await safe_inner_text(page.locator("body"))
                if re.search(r"no longer|expired|closed", body, re.I):
                    return result(SKIPPED, "job no longer active")
                return result(FAILED, "Apply button not found on job page")
            if dry_run:
                return result(DRY_RUN, "Apply button found; not clicked (dry run)")

            url_before = page.url
            if not await _click_apply(page, btn):
                await _dump_debug(page, "apply-click-failed")
                return result(FAILED, "couldn't click Apply on the job page (debug capture saved in data/debug)")
            clicked_modal_apply = False
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                await asyncio.sleep(1.5)
                if "/login" in page.url or "/signup" in page.url:
                    return result(FAILED, "Instahyre redirected to login; session expired. Log in again.")
                # Always decline "apply to similar jobs in bulk".
                cancel = await first_visible(page, ["button[ng-click='applyBulkCancel()']"])
                if cancel is not None:
                    await cancel.click()
                    return result(APPLIED, "applied (declined bulk-apply prompt)")
                if await first_visible(page, ["button:text-is('Applied')", "span:text-is('Applied')"]):
                    return result(APPLIED, "applied")
                toast = await first_visible(page, [".toast", ".alert-success", "[class*='success']",
                                                   "[role='alert']"])
                if toast is not None and SUCCESS_RE.search(await safe_inner_text(toast)):
                    return result(APPLIED, "applied")
                # Logged-in "Apply now" may lead to the opportunities modal with its own Apply.
                if not clicked_modal_apply and page.url != url_before:
                    modal_btn = await first_visible(page, ["button[ng-click*='submitChoice']",
                                                           ".apply button:has-text('Apply')"])
                    if modal_btn is not None:
                        await human_pause(0.8, 1.6)
                        await modal_btn.click()
                        clicked_modal_apply = True
                        continue
                if await first_visible(page, [".modal.in textarea", "[role='dialog'] textarea",
                                              ".modal.in input[type='text']"]):
                    return result(FAILED, "Instahyre asked for additional input (form) - not automated")
            await _dump_debug(page, "no-confirmation")
            return result(FAILED, "no confirmation after clicking Apply (check the job manually; "
                          "debug capture saved in data/debug)")
