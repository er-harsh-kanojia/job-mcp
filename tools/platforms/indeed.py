"""Indeed India (in.indeed.com) adapter.

Indeed sits behind aggressive bot protection (Cloudflare / hCaptcha), so:
  * everything runs in the headed persistent profile with human-like pauses,
  * bot checks ("Additional Verification Required" / "Verify you are human") are
    handled human-in-the-loop only, via tools.browser.wait_for_human_challenge:
    in a headed interactive run the user solves it in the window (we wait up to
    120 s); headless / MCP runs fail soft (search -> [], apply ->
    {"status": "failed", "error": "captcha_required"}). No automated solving.
  * results are read from the page's embedded ``window.mosaic.providerData
    ["mosaic-provider-jobcards"]`` JSON, falling back to DOM cards.

Only "Easily apply" (Indeed Apply) jobs are appliable. The Indeed Apply flow on
smartapply.indeed.com is walked step by step; each step's visible fields are
filled from the profile/autofill. Unknown non-optional fields stop the flow and
are reported instead of guessed. A dry run walks the steps but never clicks the
final "Submit your application" button.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from urllib.parse import quote_plus

from ..browser import (CAPTCHA_REQUIRED, captcha_hint, cookie_names, first_visible, human_pause,
                       human_scroll, safe_inner_text, wait_for_human_challenge)
from ..config import resume_path
from ..normalize import (coerce_int, days_since_epoch_ms, parse_experience, parse_posted_days,
                         split_skills, strip_html)
from .base import APPLIED, DRY_RUN, FAILED, SKIPPED, PlatformAdapter, result
from .forms import fill_visible_form, visible_errors

BASE = "https://in.indeed.com"
PAGE_SIZE = 15

CHALLENGE_WAIT = 120.0
SUBMIT_RE = re.compile(r"submit( your)? application|^submit$|send application", re.I)
SUCCESS_RE = re.compile(r"application (has been )?submitted|your application has been (submitted|sent)|you.ve applied|application sent", re.I)

APPLY_BUTTONS = ["#indeedApplyButton", "button[id*='indeedApplyButton']",
                 "[data-testid='indeedApplyButton-test']", "button[aria-label*='Apply now' i]",
                 "button:has-text('Apply now')", "button:has-text('Easily apply')"]
EXTERNAL_BUTTONS = ["button:has-text('Apply on company site')", "a:has-text('Apply on company site')",
                    "#applyButtonLinkContainer a", "[data-testid*='company-site' i]"]
CONTINUE_BUTTONS = ["button[data-testid*='continue-button' i]", "button:has-text('Continue')",
                    "button:has-text('Review your application')", "button:has-text('Next')"]
SUBMIT_BUTTONS = ["button:has-text('Submit your application')", "button:has-text('Submit application')",
                  "button[data-testid*='submit' i]"]

_MOSAIC_JS = """() => {
  try {
    const d = window.mosaic && window.mosaic.providerData && window.mosaic.providerData['mosaic-provider-jobcards'];
    return d && d.metaData && d.metaData.mosaicProviderJobCardsModel ? d.metaData.mosaicProviderJobCardsModel.results : null;
  } catch (e) { return null; }
}"""
_MOSAIC_RE = re.compile(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.+?\});\s*\n', re.S)

_DOM_JS = r"""() => Array.from(document.querySelectorAll('div.job_seen_beacon, td.resultContent, li div.cardOutline'))
  .map(c => {
    const a = c.querySelector('a[data-jk], h2.jobTitle a, a.jcs-JobTitle');
    const t = (s) => { const e = c.querySelector(s); return e ? e.innerText.trim() : ''; };
    return {
      jk: a ? (a.getAttribute('data-jk') || (a.href.match(/jk=([a-z0-9]+)/i) || [])[1] || '') : '',
      title: a ? (a.innerText || a.getAttribute('title') || '').trim() : '',
      company: t('[data-testid="company-name"], .companyName'),
      location: t('[data-testid="text-location"], .companyLocation'),
      salary: t('[data-testid="attribute_snippet_testid"], .salary-snippet-container, .metadata.salary-snippet-container'),
      snippet: t('.job-snippet, [data-testid="jobsnippet_footer"], ul'),
      posted: t('[data-testid="myJobsStateDate"], span.date'),
      easy: /easily apply|indeed apply/i.test(c.innerText) || !!c.querySelector('[data-testid="indeedApply"], .iaLabel'),
    };
  })"""


def build_search_url(keywords: list[str], location: str, start: int = 0) -> str:
    q = " ".join(k.strip() for k in keywords if k.strip())
    loc = (location or "").strip()
    url = f"{BASE}/jobs?q={quote_plus(q)}"
    if loc and loc.lower() != "india":
        url += f"&l={quote_plus(loc)}"
    if start:
        url += f"&start={start}"
    return url


def _salary(r: dict) -> str:
    snip = (r.get("salarySnippet") or {}).get("text") if isinstance(r.get("salarySnippet"), dict) else None
    if snip:
        return strip_html(snip)
    ex = r.get("extractedSalary") or {}
    if isinstance(ex, dict) and (ex.get("min") or ex.get("max")):
        lo, hi = ex.get("min"), ex.get("max")
        period = ex.get("type") or "year"
        if lo and hi and lo != hi:
            return f"₹{int(lo):,} - ₹{int(hi):,} a {period}"
        return f"₹{int(lo or hi):,} a {period}"
    return ""


def _taxonomy_skills(r: dict) -> list[str]:
    out = []
    for group in r.get("taxonomyAttributes") or []:
        if isinstance(group, dict) and "skill" in str(group.get("label", "")).lower():
            out.extend(a.get("label", "") for a in group.get("attributes") or [] if isinstance(a, dict))
    return split_skills(out)


def parse_mosaic_result(r: dict) -> dict | None:
    if not isinstance(r, dict):
        return None
    jk = r.get("jobkey") or r.get("jobKey")
    title = r.get("displayTitle") or r.get("title")
    if not jk or not title:
        return None
    snippet = strip_html(r.get("snippet") or "")
    lo, hi = parse_experience(f"{title} {snippet}")
    days = parse_posted_days(r.get("formattedRelativeTime") or "")
    if days < 0:
        days = days_since_epoch_ms(r.get("pubDate") or r.get("createDate"))
    loc = r.get("formattedLocation") or r.get("jobLocationCity") or ""
    if r.get("remoteLocation") and "remote" not in loc.lower():
        loc = f"{loc} (Remote)".strip() if loc else "Remote"
    return {
        "platform": "indeed",
        "job_id": str(jk),
        "title": strip_html(title),
        "company": strip_html(r.get("company") or r.get("truncatedCompany") or ""),
        "location": loc,
        "salary": _salary(r),
        "apply_url": f"{BASE}/viewjob?jk={jk}",
        "description": snippet,
        "skills": _taxonomy_skills(r),
        "exp_min": lo,
        "exp_max": hi,
        "posted_days_ago": days,
        "easy_apply": bool(r.get("indeedApplyEnabled") or r.get("indeedApplyable")),
    }


def parse_dom_card(d: dict) -> dict | None:
    if not d.get("jk") or not d.get("title"):
        return None
    lo, hi = parse_experience(f"{d['title']} {d.get('snippet', '')}")
    return {
        "platform": "indeed", "job_id": d["jk"], "title": d["title"],
        "company": d.get("company", ""), "location": d.get("location", ""),
        "salary": d.get("salary", ""), "apply_url": f"{BASE}/viewjob?jk={d['jk']}",
        "description": d.get("snippet", ""), "skills": [], "exp_min": lo, "exp_max": hi,
        "posted_days_ago": parse_posted_days(d.get("posted", "")), "easy_apply": bool(d.get("easy")),
    }


class IndeedAdapter(PlatformAdapter):
    name = "indeed"
    login_url = ("https://secure.indeed.com/auth?hl=en_IN&co=IN"
                 "&continue=https%3A%2F%2Fin.indeed.com%2F")
    home_url = f"{BASE}/"
    login_email_selectors = ["input[type='email']", "input[name='__email']"]
    search_timeout = 200.0  # leaves time to solve a bot check by hand (120 s)

    async def is_logged_in(self, page) -> bool:
        url = page.url or ""
        if "secure.indeed.com/auth" in url or "/account/login" in url:
            return False
        names = await cookie_names(page.context, BASE) | await cookie_names(page.context, "https://secure.indeed.com")
        if {"SHOE", "SOCK", "PPID"} & names:
            return True
        return await first_visible(page, ["[data-gnav-element-name='AccountMenu']", "#AccountMenu",
                                          "button[aria-label*='Account' i]"]) is not None

    def _captcha_failure(self, **extra) -> dict:
        return result(FAILED, CAPTCHA_REQUIRED, hint=captcha_hint(self.name), **extra)

    async def _extract(self, page) -> list[dict]:
        results = None
        try:
            results = await page.evaluate(_MOSAIC_JS)
        except Exception:
            results = None
        if not results:
            try:
                m = _MOSAIC_RE.search(await page.content())
                if m:
                    data = json.loads(m.group(1))
                    results = data["metaData"]["mosaicProviderJobCardsModel"]["results"]
            except Exception:
                results = None
        if results:
            return [x for x in (parse_mosaic_result(r) for r in results) if x]
        try:
            cards = await page.evaluate(_DOM_JS)
        except Exception:
            cards = []
        jobs = [x for x in (parse_dom_card(c) for c in cards) if x]
        if jobs:
            self.log.info("indeed: used DOM fallback (%d jobs)", len(jobs))
        return jobs

    # ---------------------------------------------------------------- search
    async def search(self, keywords, location, experience_years, limit=40):
        out: list[dict] = []
        seen: set[str] = set()
        async with self.browser() as ctx:
            page = await self.page()
            start = 0
            for _ in range(3):
                await page.goto(build_search_url(keywords, location, start),
                                wait_until="domcontentloaded", timeout=60_000)
                await human_pause(2.0, 4.0)
                if not await wait_for_human_challenge(page, self.name, CHALLENGE_WAIT):
                    self.log.warning("indeed: bot check not solved; returning %d jobs", len(out))
                    self.search_issue = CAPTCHA_REQUIRED
                    break
                try:
                    await page.wait_for_selector("div.job_seen_beacon, #mosaic-provider-jobcards, .jobsearch-NoResult-messageContainer",
                                                 timeout=15_000)
                except Exception:
                    pass
                await human_scroll(page, 2)
                batch = [j for j in await self._extract(page) if j["job_id"] not in seen]
                for j in batch:
                    seen.add(j["job_id"])
                out.extend(batch)
                if len(out) >= limit or len(batch) < 10:
                    break
                start += 10
                await human_pause(3.0, 6.0)
        return out[:limit]

    # ----------------------------------------------------------------- apply
    async def apply(self, job, profile, dry_run=True):
        if not job.get("easy_apply"):
            return result(SKIPPED, "not an Indeed Apply ('Easily apply') job", easy_apply=False)
        async with self.browser() as ctx:
            page = await self.page()
            extra_pages_before = set(id(p) for p in ctx.pages)
            try:
                return await self._apply(ctx, page, job, profile, dry_run)
            finally:
                for p in list(ctx.pages):
                    if id(p) not in extra_pages_before and p is not page and not p.is_closed():
                        try:
                            await p.close()
                        except Exception:
                            pass

    async def _apply(self, ctx, page, job, profile, dry_run):
        await page.goto(job["apply_url"], wait_until="domcontentloaded", timeout=60_000)
        await human_pause(2.0, 4.0)
        if not await wait_for_human_challenge(page, self.name, CHALLENGE_WAIT):
            return self._captcha_failure()
        if not await self.is_logged_in(page):
            return result(FAILED, "Not logged in to Indeed. Run login (run.py option 1) first.")
        await human_scroll(page, 1)

        body = await safe_inner_text(page.locator("body"))
        if re.search(r"\bYou applied\b|\bApplied\b on|already applied", body):
            return result(SKIPPED, "already applied (detected on site)")
        btn = await first_visible(page, APPLY_BUTTONS, timeout_ms=8000)
        if btn is None:
            if await first_visible(page, EXTERNAL_BUTTONS):
                return result(SKIPPED, "external job: applies on company site", easy_apply=False)
            if re.search(r"this job has expired|no longer available", body, re.I):
                return result(SKIPPED, "job expired")
            return result(FAILED, "Indeed Apply button not found")

        # The apply form opens in a new tab or in the same tab.
        form = page
        try:
            async with ctx.expect_page(timeout=10_000) as pinfo:
                await btn.click()
            form = await pinfo.value
        except Exception:
            form = page
        try:
            await form.wait_for_load_state("domcontentloaded", timeout=30_000)
        except Exception:
            pass

        return await self._walk_form(form, profile, dry_run)

    async def _walk_form(self, form, profile, dry_run) -> dict:
        resume = resume_path()
        steps, all_filled = [], []
        last_url, same_url_count = None, 0
        for step in range(15):
            await human_pause(1.8, 3.5)
            if not await wait_for_human_challenge(form, self.name, CHALLENGE_WAIT):
                return self._captcha_failure(steps=steps)
            body = await safe_inner_text(form.locator("body"))
            if SUCCESS_RE.search(body) or "post-apply" in form.url:
                return result(APPLIED, "applied", steps=steps, filled=all_filled)

            heading = (await safe_inner_text(form.locator("h1, h2").first))[:120]
            steps.append(heading or form.url.split("?")[0][-60:])

            if "resume" in form.url.lower() or re.search(r"\bresume\b|\bCV\b", heading, re.I):
                await self._handle_resume_step(form, resume)
            else:
                res = await fill_visible_form(form, profile, resume, treat_unlabelled_as_required=True)
                all_filled.extend(res["filled"])
                if res["unanswered"]:
                    return result(FAILED, "Unknown required field(s) on Indeed form: "
                                  + "; ".join(q[:80] for q in res["unanswered"][:5]),
                                  steps=steps, filled=all_filled, unanswered=res["unanswered"])

            submit = await first_visible(form, SUBMIT_BUTTONS)
            if submit is not None and SUBMIT_RE.search(await safe_inner_text(submit)):
                if dry_run:
                    return result(DRY_RUN, f"reached the submit step after {step + 1} step(s); not submitted",
                                  steps=steps, filled=all_filled)
                await submit.click()
                for _ in range(15):
                    await asyncio.sleep(1.5)
                    if SUCCESS_RE.search(await safe_inner_text(form.locator("body"))) or "post-apply" in form.url:
                        return result(APPLIED, "applied", steps=steps, filled=all_filled)
                errs = await visible_errors(form)
                return result(FAILED, "submitted but no confirmation seen" + (f": {errs[0]}" if errs else ""),
                              steps=steps, filled=all_filled)

            cont = await first_visible(form, CONTINUE_BUTTONS, timeout_ms=4000)
            if cont is None:
                return result(FAILED, f"unrecognised Indeed Apply step: {heading or form.url[:80]}",
                              steps=steps, filled=all_filled)
            label = await safe_inner_text(cont)
            if SUBMIT_RE.search(label):  # safety net: never submit from the continue path
                if dry_run:
                    return result(DRY_RUN, "reached the submit step; not submitted", steps=steps, filled=all_filled)
            url_before = form.url
            await cont.click()
            await human_pause(1.5, 3.0)
            if form.url == url_before:
                errs = await visible_errors(form)
                same_url_count += 1
                if errs and same_url_count >= 2:
                    return result(FAILED, "Indeed form rejected input: " + " | ".join(errs[:3]),
                                  steps=steps, filled=all_filled)
                if same_url_count >= 3:
                    return result(FAILED, f"stuck on Indeed step: {heading}", steps=steps, filled=all_filled)
            else:
                same_url_count = 0
            last_url = form.url
        return result(FAILED, "too many Indeed Apply steps", steps=steps, filled=all_filled)

    async def _handle_resume_step(self, form, resume) -> None:
        # Prefer the resume already on the Indeed profile; else upload the configured file.
        card = await first_visible(form, ["[data-testid*='resume-selection-file-resume' i]",
                                          "[data-testid*='IndeedResumeCard' i]",
                                          "[data-testid*='resume-card' i]"])
        if card is not None:
            try:
                checked = await card.locator("input[type=radio]").first.is_checked(timeout=1500)
            except Exception:
                checked = False
            if not checked:
                try:
                    await card.click()
                except Exception:
                    pass
            return
        if resume is not None:
            file_input = form.locator("input[type=file]").first
            if await file_input.count():
                await file_input.set_input_files(str(resume))
                await human_pause(2.0, 4.0)
