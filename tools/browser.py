"""Playwright helpers: one persistent (cookie-keeping) browser profile per platform.

Profiles live in ``<project>/.sessions/<platform>``. A profile directory can only
be opened by one browser at a time, so access is serialised per platform with
an asyncio lock (within this process).

Environment overrides:
    JOB_MCP_HEADLESS=1          run headless (default: headed, which is far less
                                likely to trip bot protection)
    JOB_MCP_BROWSER_CHANNEL     e.g. "chrome" or "msedge" to use an installed
                                browser instead of Playwright's bundled Chromium
    JOB_MCP_USER_AGENT          force a specific user agent string
    JOB_MCP_SESSIONS_DIR        alternative directory for the profiles
    JOB_MCP_NONINTERACTIVE=1    never wait for a human to solve a captcha (set by
                                server.py); fail soft with "captcha_required"

Bot checks (Cloudflare "Verify you are human", etc.) are handled human-in-the-loop
only: in a headed, interactive run we ask the user to solve the check in the
visible window and wait. There is deliberately no automated captcha solving and
no fingerprint spoofing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from .config import ROOT_DIR

log = logging.getLogger("job_mcp.browser")

LOGIN_MARKER = ".job_mcp_login.json"

_platform_locks: dict[str, asyncio.Lock] = {}
_browser_version: str | None = None



def sessions_dir() -> Path:
    return Path(os.environ.get("JOB_MCP_SESSIONS_DIR") or (ROOT_DIR / ".sessions"))


def session_dir(platform: str) -> Path:
    return sessions_dir() / platform


def has_session(platform: str) -> bool:
    """True if a browser profile exists for the platform and a login was recorded."""
    return (session_dir(platform) / LOGIN_MARKER).is_file()


def session_info(platform: str) -> dict:
    """Metadata recorded by interactive_login (no secrets)."""
    marker = session_dir(platform) / LOGIN_MARKER
    info = {"platform": platform, "profile_exists": session_dir(platform).is_dir(),
            "logged_in_recorded": marker.is_file()}
    if marker.is_file():
        try:
            info.update(json.loads(marker.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return info


def mark_logged_in(platform: str) -> None:
    d = session_dir(platform)
    d.mkdir(parents=True, exist_ok=True)
    (d / LOGIN_MARKER).write_text(
        json.dumps({"logged_in_at": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")


def clear_login_marker(platform: str) -> None:
    try:
        (session_dir(platform) / LOGIN_MARKER).unlink()
    except FileNotFoundError:
        pass


def headless_default() -> bool:
    return os.environ.get("JOB_MCP_HEADLESS", "").strip().lower() in ("1", "true", "yes")


def _lock_for(platform: str) -> asyncio.Lock:
    lock = _platform_locks.get(platform)
    if lock is None:
        lock = _platform_locks[platform] = asyncio.Lock()
    return lock


async def _detect_browser_version(pw) -> str:
    """Major.minor version of the browser we launch, for a consistent user agent."""
    global _browser_version
    if _browser_version:
        return _browser_version
    channel = os.environ.get("JOB_MCP_BROWSER_CHANNEL") or None
    try:
        browser = await pw.chromium.launch(headless=True, channel=channel)
        _browser_version = browser.version
        await browser.close()
    except Exception as exc:  # pragma: no cover - environment dependent
        log.debug("Could not detect browser version: %s", exc)
        _browser_version = "130.0.0.0"
    return _browser_version


def build_user_agent(version: str) -> str:
    """A normal desktop Chrome UA (reduced format, as real Chrome sends)."""
    major = (version or "130").split(".")[0]
    return (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")


@asynccontextmanager
async def open_context(platform: str, headless: bool | None = None) -> AsyncIterator:
    """Open the persistent browser context for ``platform``.

    Usage::

        async with open_context("naukri") as ctx:
            page = await new_page(ctx)
    """
    from playwright.async_api import async_playwright  # imported lazily

    if headless is None:
        headless = headless_default()
    udir = session_dir(platform)
    udir.mkdir(parents=True, exist_ok=True)
    channel = os.environ.get("JOB_MCP_BROWSER_CHANNEL") or None

    async with _lock_for(platform):
        async with async_playwright() as pw:
            ua = os.environ.get("JOB_MCP_USER_AGENT") or build_user_agent(
                await _detect_browser_version(pw))
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=str(udir),
                headless=headless,
                channel=channel,
                user_agent=ua,
                viewport={"width": 1366, "height": 860},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                args=["--no-first-run", "--no-default-browser-check"],
            )
            ctx.set_default_timeout(20_000)
            try:
                yield ctx
            finally:
                try:
                    await ctx.close()
                except Exception:  # browser may already be closed by the user
                    pass


async def new_page(ctx):
    """Reuse the blank tab a persistent context opens with, else open a new one."""
    for p in ctx.pages:
        if p.url in ("about:blank", "") and not p.is_closed():
            return p
    return await ctx.new_page()


async def human_pause(lo: float = 0.8, hi: float = 2.2) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


async def human_scroll(page, steps: int = 3) -> None:
    for _ in range(steps):
        try:
            await page.mouse.wheel(0, random.randint(300, 700))
        except Exception:
            return
        await asyncio.sleep(random.uniform(0.3, 0.9))


async def cookie_names(ctx, url: str) -> set[str]:
    try:
        return {c["name"] for c in await ctx.cookies(url)}
    except Exception:
        return set()


async def first_visible(page, selectors: list[str], timeout_ms: int = 0):
    """Return the first visible locator among ``selectors`` (or None)."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    return loc
            except Exception:
                continue
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(0.4)


async def safe_inner_text(locator, default: str = "") -> str:
    try:
        return (await locator.inner_text(timeout=3000)).strip()
    except Exception:
        return default


# ------------------------------------------------------------ bot challenges

CAPTCHA_REQUIRED = "captcha_required"

_CHALLENGE_TEXT_RE = re.compile(
    r"additional verification required|verify you are human|verifying you are human|"
    r"checking (if the site connection is secure|your browser)|"
    r"needs to review the security of your connection", re.I)
_CHALLENGE_TITLE_RE = re.compile(r"^\s*(just a moment|attention required|security check)", re.I)
_CHALLENGE_MARKUP_RE = re.compile(r"challenges\.cloudflare\.com|cf-chl|cf_chl_|/cdn-cgi/challenge-platform", re.I)


def is_challenge(html: str = "", title: str = "", url: str = "") -> bool:
    """Pure check: does this page look like a Cloudflare-style bot challenge?"""
    if url and _CHALLENGE_MARKUP_RE.search(url):
        return True
    if title and _CHALLENGE_TITLE_RE.search(title):
        return True
    if html and (_CHALLENGE_MARKUP_RE.search(html) or _CHALLENGE_TEXT_RE.search(html)):
        return True
    return False


async def detect_challenge(page) -> bool:
    """True if the page currently shows a bot challenge."""
    try:
        title = await page.title()
    except Exception:
        title = ""
    url = page.url or ""
    frames = " ".join(f.url for f in page.frames if f.url)
    text = await safe_inner_text(page.locator("body"))
    return is_challenge(f"{frames} {text[:3000]}", title, url)


def interactive_allowed(headless: bool | None = None) -> bool:
    if os.environ.get("JOB_MCP_NONINTERACTIVE", "").strip().lower() in ("1", "true", "yes"):
        return False
    return not (headless_default() if headless is None else headless)


def captcha_hint(platform: str) -> str:
    return (f"{platform} is showing a 'verify you are human' check. Run `python run.py`, choose "
            f"1 (Login) -> {platform}, and solve the check once in the browser window; the "
            f"persistent profile keeps the clearance cookie for later runs.")


async def wait_for_human_challenge(page, platform: str, timeout: float = 120.0,
                                   headless: bool | None = None) -> bool:
    """If a challenge is shown, wait for the user to solve it manually.

    Returns True when no challenge is (or remains) on the page. Returns False
    immediately when running headless / non-interactive, or after ``timeout``.
    """
    if not await detect_challenge(page):
        return True
    if not interactive_allowed(headless):
        logging.getLogger("job_mcp.browser").warning("%s", captcha_hint(platform))
        return False
    msg = (f"\n  >>> {platform.capitalize()} is showing a captcha. Solve it in the browser window; "
           f"waiting up to {int(timeout)}s ...\n")
    print(msg, file=sys.stderr, flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(2.5)
        if page.is_closed():
            return False
        if not await detect_challenge(page):
            await asyncio.sleep(2.0)  # let the page finish loading after clearance
            return True
    logging.getLogger("job_mcp.browser").warning("%s", captcha_hint(platform))
    return False
