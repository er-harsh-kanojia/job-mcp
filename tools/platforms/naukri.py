"""Naukri.com adapter.

Search: load the normal search-results page inside the (logged-in) persistent
browser and capture the JSON the page itself fetches from ``/jobapi/v3/search``
(plain HTTP calls to that API are blocked with "recaptcha required"). Fallbacks:
an in-page ``fetch`` with the site's headers, then DOM scraping of result cards.

Apply: open the job page, click "Apply", answer the chatbot questionnaire drawer
from config.autofill. "Apply on company site" jobs are skipped.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
from urllib.parse import parse_qs, quote, urlsplit

from ..autofill import answer_question
from ..browser import (cookie_names, first_visible, human_pause, human_scroll,
                       safe_inner_text)
from ..config import data_dir
from ..normalize import (coerce_int, days_since_epoch_ms, parse_experience,
                         parse_posted_days, slugify, split_skills, strip_html)
from .base import APPLIED, DRY_RUN, FAILED, SKIPPED, PlatformAdapter, result

log = logging.getLogger("job_mcp.naukri")

# How long to wait for the person to answer a chatbot question autofill can't answer.
HUMAN_WAIT = int(os.environ.get("JOB_MCP_HUMAN_WAIT_SECONDS", "180"))

BASE = "https://www.naukri.com"
API_PATH = "/jobapi/v3/search"
API_HEADERS = {
    "appid": "109",
    "systemid": "Naukri",
    "clientid": "d3skt0p",
    "gid": "LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE",
    "accept": "application/json",
}
PAGE_SIZE = 20

SUCCESS_RE = re.compile(r"successfully applied|applied successfully|you have (successfully )?applied|application (has been )?(sent|submitted)|\bapplied to [\"“']", re.I)


def _option_index(labels: list[str], answer: str | None) -> int | None:
    """Position of the answer among the visible options (whitespace/case-insensitive), or None."""
    if answer is None:
        return None
    want = " ".join(str(answer).split()).lower()
    for i, label in enumerate(labels):
        if " ".join((label or "").split()).lower() == want:
            return i
    return None


async def _option_label(el) -> str:
    """Visible text of a radio/checkbox/chip, falling back to its label, aria-label or value."""
    text = (await safe_inner_text(el)).strip()
    if text:
        return text
    for attr in ("aria-label", "value", "title"):
        try:
            v = await el.get_attribute(attr)
        except Exception:
            v = None
        if v and v.strip():
            return v.strip()
    try:
        v = await el.evaluate("e => (e.closest('label') || e.parentElement || e).innerText || ''")
        return (v or "").strip()
    except Exception:
        return ""


def save_apply_outcome(url: str) -> tuple[bool, str] | None:
    """Read the result of Naukri's post-apply redirect.

    After a successful Apply, Naukri navigates to ``/myapply/saveApply?...&multiApplyResp={"<jobId>":200}``.
    Returns (all accepted, codes) for that page, or None for any other URL.
    """
    parts = urlsplit(url or "")
    if "/myapply/saveApply" not in parts.path:
        return None
    raw = (parse_qs(parts.query).get("multiApplyResp") or [""])[0]
    try:
        codes = json.loads(raw) if raw else {}
    except ValueError:
        codes = {}
    if not isinstance(codes, dict) or not codes:
        return True, "no response codes"  # the saveApply page itself means the apply was saved
    ok = all(str(v) == "200" for v in codes.values())
    return ok, ",".join(f"{k}:{v}" for k, v in codes.items())
CLOSING_RE = re.compile(r"^\s*(thank(s| you)\b.*\b(responses?|answers?|time|applying)|we have received|your application (is|has been))", re.I)
EXPIRED_RE = re.compile(r"no longer (accepting|available)|job (has )?expired|this job is closed", re.I)

# Chatbot questionnaire selectors (several fallbacks; the class names are hashed-ish
# and change occasionally).
CHAT_DRAWER = [".chatbot_DrawerContentWrapper", "[class*='chatbot_Drawer']",
               "[class*='chatbot_MessageContainer']", "div[id*='_chatbot']"]
CHAT_BOT_MSG = ".botMsg, li.botItem, [class*='botItem'], [class*='botMsg']"
CHAT_RADIO = ".ssrc__radio-btn-container, [class*='radio-btn-container']"
CHAT_CHECKBOX = ".mcc__checkbox-container, [class*='mcc__checkbox'], [class*='checkbox-container']"
CHAT_CHIP = ".chatbot_Chip, [class*='chatbot_Chip'], [class*='chipItem']"
CHAT_INPUT = ["div.textArea[contenteditable='true']", "[id$='InputBox'][contenteditable='true']",
              "[class*='chatbot'] [contenteditable='true']", "[class*='chatbot'] input[type='text']",
              "[class*='chatbot'] textarea"]
CHAT_SEND = [".sendMsg", "[class*='sendMsg']", "[class*='chatbot'] button:has-text('Save')",
             "[class*='chatbot'] button:has-text('Submit')", "[class*='chatbot'] button:has-text('Send')"]


def build_search_url(keywords: list[str], location: str, experience_years: int | None,
                     page_no: int = 1) -> str:
    kstr = ", ".join(k.strip() for k in keywords if k.strip())
    loc = (location or "").strip()
    path = f"{slugify(kstr) or 'jobs'}-jobs"
    if loc:
        path += f"-in-{slugify(loc)}"
    if page_no > 1:
        path += f"-{page_no}"
    url = f"{BASE}/{path}?k={quote(kstr)}"
    if loc:
        url += f"&l={quote(loc.lower())}"
    if experience_years is not None and experience_years >= 0:
        url += f"&experience={int(experience_years)}"
    return url


def api_params(keywords: list[str], location: str, experience_years: int | None,
               page_no: int = 1) -> dict:
    kstr = ", ".join(k.strip() for k in keywords if k.strip())
    seo = f"{slugify(kstr)}-jobs" + (f"-in-{slugify(location)}" if location else "")
    p = {"noOfResults": str(PAGE_SIZE), "urlType": "search_by_key_loc" if location else "search_by_keyword",
         "searchType": "adv", "keyword": kstr, "pageNo": str(page_no), "k": kstr,
         "seoKey": seo + (f"-{page_no}" if page_no > 1 else ""), "src": "jobsearchDesk", "latLong": ""}
    if location:
        p["location"] = location.lower()
        p["l"] = location.lower()
    if experience_years is not None and experience_years >= 0:
        p["experience"] = str(int(experience_years))
    return p


def parse_api_job(j: dict) -> dict | None:
    """Convert one ``jobDetails`` item from /jobapi/v3/search."""
    if not isinstance(j, dict):
        return None
    title = j.get("title") or ""
    url = j.get("jdURL") or j.get("jdUrl") or ""
    if url.startswith("/"):
        url = BASE + url
    if not title or not url:
        return None
    ph = {}
    for p in j.get("placeholders") or []:
        if isinstance(p, dict) and p.get("type"):
            ph[p["type"]] = p.get("label") or ""
    lo, hi = parse_experience(ph.get("experience") or j.get("experienceText") or "")
    if lo < 0:
        lo = coerce_int(j.get("minimumExperience"))
        hi = coerce_int(j.get("maximumExperience"))
    days = parse_posted_days(j.get("footerPlaceholderLabel") or "")
    if days < 0:
        days = days_since_epoch_ms(j.get("createdDate"))
    external = bool(j.get("companyApplyUrl") or j.get("applyRedirectUrl") or j.get("externalApplyUrl"))
    return {
        "platform": "naukri",
        "job_id": str(j.get("jobId") or ""),
        "title": strip_html(title),
        "company": strip_html(j.get("companyName") or ""),
        "location": ph.get("location") or "",
        "salary": ph.get("salary") or "",
        "apply_url": url.split("?")[0],
        "description": strip_html(j.get("jobDescription") or "", max_len=1500),
        "skills": split_skills(j.get("tagsAndSkills") or ""),
        "exp_min": lo,
        "exp_max": hi,
        "posted_days_ago": days,
        "easy_apply": not external,
    }


# DOM fallback: Naukri SRP job cards.
_DOM_JS = r"""
() => {
  const txt = (root, sels) => { for (const s of sels) { const e = root.querySelector(s); if (e && e.innerText.trim()) return e.innerText.trim(); } return ''; };
  const cards = document.querySelectorAll('div.srp-jobtuple-wrapper, div.cust-job-tuple, article.jobTuple');
  return Array.from(cards).map(c => {
    const a = c.querySelector('a.title, a[class*=title]');
    return {
      job_id: c.getAttribute('data-job-id') || '',
      title: a ? (a.getAttribute('title') || a.innerText).trim() : '',
      url: a ? a.href : '',
      company: txt(c, ['a.comp-name', '.comp-name', 'a.subTitle', '[class*=comp-name]']),
      exp: txt(c, ['.expwdth', '.exp-wrap', 'li.experience', '[class*=exp]']),
      location: txt(c, ['.locWdth', '.loc-wrap', 'li.location', '[class*=loc]']),
      salary: txt(c, ['.sal-wrap span', '.sal', 'li.salary', '[class*=sal]']),
      desc: txt(c, ['.job-desc', '.job-description', '[class*=job-desc]']),
      skills: Array.from(c.querySelectorAll('ul.tags-gt li, ul.tags li, [class*=tag] li')).map(e => e.innerText.trim()),
      posted: txt(c, ['.job-post-day', '[class*=post-day]', '.type br + span', '.fleft.postedDate']),
    };
  });
}
"""


def parse_dom_job(d: dict) -> dict | None:
    if not d.get("title") or not d.get("url"):
        return None
    lo, hi = parse_experience(d.get("exp", ""))
    return {
        "platform": "naukri",
        "job_id": d.get("job_id") or (re.search(r"(\d{9,})", d["url"]) or [""])[0],
        "title": d["title"], "company": d.get("company", ""), "location": d.get("location", ""),
        "salary": d.get("salary", ""), "apply_url": d["url"].split("?")[0],
        "description": d.get("desc", ""), "skills": d.get("skills") or [],
        "exp_min": lo, "exp_max": hi, "posted_days_ago": parse_posted_days(d.get("posted", "")),
        "easy_apply": True,
    }


class NaukriAdapter(PlatformAdapter):
    name = "naukri"
    login_url = f"{BASE}/nlogin/login"
    home_url = f"{BASE}/mnjuser/homepage"
    login_email_selectors = ["#usernameField", "input[placeholder*='Email' i]", "input[type='email']"]
    search_timeout = 120.0

    async def is_logged_in(self, page) -> bool:
        if "nlogin" in (page.url or ""):
            return False
        names = await cookie_names(page.context, BASE)
        if {"nauk_at", "nauk_rt"} & names:
            return True
        marker = await first_visible(page, [
            ".nI-gNb-drawer__icon", ".nI-gNb-icon-img", "a[href*='/mnjuser/profile']",
            "div.nI-gNb-info__sub-link"])
        return marker is not None

    # ---------------------------------------------------------------- search
    async def _capture_api(self, page, url: str) -> dict | None:
        try:
            async with page.expect_response(
                    lambda r: API_PATH in r.url and r.request.method == "GET", timeout=30_000) as info:
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            resp = await info.value
            if resp.ok:
                return await resp.json()
            self.log.warning("naukri: search API returned HTTP %s", resp.status)
        except Exception as exc:
            self.log.info("naukri: no search API response captured (%s)", type(exc).__name__)
        return None

    async def _fetch_api(self, page, params: dict) -> dict | None:
        js = """async ({params, headers}) => {
            const r = await fetch('/jobapi/v3/search?' + new URLSearchParams(params),
                                  {headers, credentials: 'include'});
            if (!r.ok) return {__status: r.status};
            return await r.json();
        }"""
        try:
            data = await page.evaluate(js, {"params": params, "headers": API_HEADERS})
            if isinstance(data, dict) and "__status" in data:
                self.log.info("naukri: in-page API fetch returned HTTP %s", data["__status"])
                return None
            return data
        except Exception as exc:
            self.log.info("naukri: in-page API fetch failed (%s)", type(exc).__name__)
            return None

    async def search(self, keywords, location, experience_years, limit=40):
        out: list[dict] = []
        pages = max(1, min(3, math.ceil(limit / PAGE_SIZE)))
        async with self.browser() as ctx:
            page = await self.page()
            for page_no in range(1, pages + 1):
                url = build_search_url(keywords, location, experience_years, page_no)
                data = await self._capture_api(page, url)
                if not (data and data.get("jobDetails")):
                    if page.url.startswith(BASE):
                        data = await self._fetch_api(
                            page, api_params(keywords, location, experience_years, page_no))
                batch: list[dict] = []
                if data and isinstance(data.get("jobDetails"), list):
                    batch = [x for x in (parse_api_job(j) for j in data["jobDetails"]) if x]
                if not batch:
                    try:
                        await page.wait_for_selector(
                            "div.srp-jobtuple-wrapper, div.cust-job-tuple, article.jobTuple", timeout=12_000)
                        batch = [x for x in (parse_dom_job(d) for d in await page.evaluate(_DOM_JS)) if x]
                        if batch:
                            self.log.info("naukri: used DOM fallback (%d jobs)", len(batch))
                    except Exception:
                        body = (await safe_inner_text(page.locator("body")))[:300].lower()
                        if "captcha" in body or "access denied" in body:
                            self.log.warning("naukri: bot check / captcha page shown; log in via run.py option 1")
                            self.search_issue = "captcha_required"
                out.extend(batch)
                total = coerce_int((data or {}).get("noOfJobs"), 0)
                if len(out) >= limit or len(batch) < PAGE_SIZE or (total and len(out) >= total):
                    break
                await human_pause(1.5, 3.5)
        return out[:limit]

    # ----------------------------------------------------------------- apply
    async def apply(self, job, profile, dry_run=True):
        async with self.browser() as ctx:
            page = await self.page()
            try:
                return await self._apply(page, job, profile, dry_run)
            finally:
                # close any extra tabs (company-site redirects) but keep the context
                for p in list(ctx.pages):
                    if p is not page and not p.is_closed():
                        try:
                            await p.close()
                        except Exception:
                            pass

    async def _apply(self, page, job, profile, dry_run):
        await page.goto(job["apply_url"], wait_until="domcontentloaded", timeout=45_000)
        await human_pause(2.0, 4.0)
        await human_scroll(page, 2)
        if not await self.is_logged_in(page):
            return result(FAILED, "Not logged in to Naukri. Run login (run.py option 1) first.")

        if await first_visible(page, ["#already-applied", "button:text-is('Applied')",
                                      "span:text-is('Applied')"]):
            return result(SKIPPED, "already applied (detected on site)")
        if await first_visible(page, ["#company-site-button", "button:has-text('Apply on company site')",
                                      "a:has-text('Apply on company site')"]):
            return result(SKIPPED, "external job: applies on company site", easy_apply=False)

        btn = await first_visible(page, ["#apply-button", "button.apply-button",
                                         "button:text-is('Apply')", "button:has-text('I am interested')"],
                                  timeout_ms=6000)
        if btn is None:
            body = await safe_inner_text(page.locator("body"))
            if EXPIRED_RE.search(body):
                return result(SKIPPED, "job expired / not accepting applications")
            return result(FAILED, "Apply button not found on job page")

        if dry_run:
            # On Naukri the Apply click itself submits when there is no questionnaire,
            # so a dry run must stop here.
            return result(DRY_RUN, "Apply button found; not clicked (dry run)")

        popup_task = asyncio.ensure_future(page.context.wait_for_event("page", timeout=8000))
        await btn.click()
        try:
            popup = await popup_task
            await popup.close()
            return result(SKIPPED, "external job: Apply opened the company site", easy_apply=False)
        except Exception:
            pass

        return await self._post_apply(page, profile)

    async def _dump_debug(self, page, tag: str) -> str:
        """Save a screenshot and the HTML of the current page to data/debug/ for diagnosis."""
        try:
            out = data_dir() / "debug"
            out.mkdir(parents=True, exist_ok=True)
            stem = out / f"naukri-{time.strftime('%Y%m%d-%H%M%S')}-{slugify(tag)[:40]}"
            await page.screenshot(path=str(stem) + ".png", full_page=True)
            (stem.parent / (stem.name + ".html")).write_text(await page.content(), encoding="utf-8")
            log.warning("naukri: saved debug capture %s.{png,html} (url %s)", stem, page.url)
            return str(stem)
        except Exception as exc:
            log.warning("naukri: debug capture failed: %s", exc)
            return ""

    async def _post_apply(self, page, profile) -> dict:
        start = time.monotonic()
        deadline = start + 150
        last_q, repeats, answered = None, 0, []
        seen_drawer = False
        human_q, human_until = None, 0.0
        while time.monotonic() < deadline:
            await asyncio.sleep(1.5)
            saved = save_apply_outcome(page.url)
            if saved is not None:
                ok, codes = saved
                if ok:
                    return result(APPLIED, "applied", answers=answered)
                return result(FAILED, f"Naukri rejected the application (response {codes})",
                              answers=answered)
            body = await safe_inner_text(page.locator("body"))
            if SUCCESS_RE.search(body) or await first_visible(page, [".apply-status-header", "#already-applied"]):
                return result(APPLIED, "applied", answers=answered)
            if "naukri.com" not in page.url:
                return result(SKIPPED, f"redirected off Naukri ({page.url[:80]})", easy_apply=False)

            drawer = await first_visible(page, CHAT_DRAWER)
            if drawer is None:
                # Neither a confirmation nor the chatbot after 30 s: our selectors don't
                # match what Naukri shows. Stop early instead of waiting the full deadline.
                if not seen_drawer and time.monotonic() - start > 30:
                    await self._dump_debug(page, "no-confirmation-no-chatbot")
                    return result(FAILED, "clicked Apply but saw neither a confirmation nor the "
                                  "questionnaire (debug capture saved in data/debug)", answers=answered)
                continue
            seen_drawer = True
            msgs = page.locator(CHAT_BOT_MSG)
            n = await msgs.count()
            if not n:
                continue
            question = (await safe_inner_text(msgs.nth(n - 1))).strip()
            if not question:
                continue
            if CLOSING_RE.search(question):
                # The chatbot's sign-off ("Thank you for your responses"), not a question:
                # keep polling for the confirmation instead of waiting for the person.
                continue
            if human_q is not None:
                # Waiting for the person to answer a question autofill couldn't.
                if question == human_q:
                    if time.monotonic() > human_until:
                        await self._dump_debug(page, "unanswered-question")
                        return result(FAILED, f"no answer within {HUMAN_WAIT}s to: {question[:150]} "
                                      "(answer it in the browser, or add details to your profile)",
                                      answers=answered)
                    continue
                answered.append({"question": human_q[:150], "answer": "(answered by you in the browser)"})
                log.info("naukri: you answered '%s'; continuing", human_q[:80])
                human_q, last_q, repeats = None, None, 0
            if question == last_q:
                repeats += 1
                if repeats >= 4:
                    return result(FAILED, f"chatbot did not accept our answer to: {question[:120]}",
                                  answers=answered)
                continue
            outcome = await self._answer_chat(page, question, profile)
            if outcome is None:
                # Leave it for the person: they can type the answer in the open browser window.
                log.warning("naukri: waiting up to %ds for you to answer in the browser: %s",
                            HUMAN_WAIT, question[:150])
                human_q, human_until = question, time.monotonic() + HUMAN_WAIT
                deadline = max(deadline, human_until + 60)
                continue
            answered.append({"question": question[:150], "answer": outcome})
            last_q, repeats = question, 0
        await self._dump_debug(page, "timeout")
        return result(FAILED, "timed out waiting for application confirmation", answers=answered)

    async def _answer_chat(self, page, question: str, profile: dict) -> str | None:
        """Answer the current chatbot question. Returns the answer or None."""
        # Radio buttons
        radios = page.locator(CHAT_RADIO)
        if await radios.count():
            labels = [await _option_label(radios.nth(i)) for i in range(await radios.count())]
            ans = answer_question(question, profile, kind="radio", options=labels)
            i = _option_index(labels, ans)
            if i is None:
                return None
            await radios.nth(i).click()
            await self._send(page)
            return ans
        # Checkboxes (multi-select): choose the single best option
        boxes = page.locator(CHAT_CHECKBOX)
        if await boxes.count():
            labels = [await _option_label(boxes.nth(i)) for i in range(await boxes.count())]
            ans = answer_question(question, profile, kind="checkbox", options=labels)
            i = _option_index(labels, ans)
            if i is None:
                return None
            await boxes.nth(i).click()
            await self._send(page)
            return ans
        # Suggestion chips (e.g. "Skip", "Immediately", "15 days")
        chips = page.locator(CHAT_CHIP)
        chip_labels = [await _option_label(chips.nth(i)) for i in range(await chips.count())]
        # Free-text input
        box = await first_visible(page, CHAT_INPUT)
        if box is not None:
            ans = answer_question(question, profile, kind="text")
            if ans is None and chip_labels:
                ans = answer_question(question, profile, kind="chips", options=chip_labels)
                i = _option_index(chip_labels, ans)
                if i is not None:
                    await chips.nth(i).click()
                    return ans
                ans = None
            if ans is None:
                return None
            await box.click()
            await page.keyboard.type(str(ans), delay=60)
            await human_pause(0.4, 0.9)
            await self._send(page)
            return ans
        if chip_labels:
            ans = answer_question(question, profile, kind="chips", options=chip_labels)
            i = _option_index(chip_labels, ans)
            if i is None:
                return None
            await chips.nth(i).click()
            return ans
        return None

    async def _send(self, page) -> None:
        btn = await first_visible(page, CHAT_SEND, timeout_ms=3000)
        if btn is not None:
            await btn.click()
        else:
            await page.keyboard.press("Enter")
        await human_pause(1.0, 2.0)
