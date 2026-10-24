"""Interactive (manual) login: open a visible browser, let the user sign in,
save the session in the platform's persistent profile.

Passwords are never typed by this code; at most the e-mail field is prefilled.
"""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlsplit

from .browser import (clear_login_marker, first_visible, has_session, mark_logged_in,
                      new_page, open_context, session_dir, session_info)
from .config import get_login_email
from .platforms import PLANNED_PLATFORMS, SUPPORTED_PLATFORMS, get_adapter

log = logging.getLogger("job_mcp.session")

__all__ = ["SUPPORTED_PLATFORMS", "PLANNED_PLATFORMS", "interactive_login",
           "check_login", "session_status", "has_session"]


async def _prefill_email(page, adapter, platform: str) -> bool:
    email = get_login_email(platform)
    if not email or not adapter.login_email_selectors:
        return False
    field = await first_visible(page, adapter.login_email_selectors, timeout_ms=8000)
    if field is None:
        return False
    try:
        if not (await field.input_value()).strip():
            await field.fill(email)
        return True
    except Exception:
        return False


async def interactive_login(platform: str, timeout_seconds: int = 300) -> dict:
    """Open a headed browser on the platform's login page and wait for the user.

    Login is detected automatically (cookies / logged-in page markers). The
    session persists in .sessions/<platform>. Closing the window ends the wait.
    """
    platform = (platform or "").strip().lower()
    if platform not in SUPPORTED_PLATFORMS:
        return {"platform": platform, "status": "error",
                "message": f"Unsupported platform. Choose from: {', '.join(SUPPORTED_PLATFORMS)}"}
    adapter = get_adapter(platform)
    started = time.monotonic()
    try:
        async with open_context(platform, headless=False) as ctx:
            adapter.context = ctx
            page = await new_page(ctx)
            # Already logged in? (e.g. re-running login)
            if await adapter.ensure_logged_in(page):
                mark_logged_in(platform)
                return {"platform": platform, "status": "logged_in", "already_logged_in": True,
                        "session_dir": str(session_dir(platform)),
                        "message": "Existing session is still valid."}
            await page.goto(adapter.login_url, wait_until="domcontentloaded", timeout=60_000)
            prefilled = await _prefill_email(page, adapter, platform)
            log.warning("[%s] Complete the login in the browser window (waiting up to %ds)...",
                        platform, timeout_seconds)
            last_seen = None
            while time.monotonic() - started < timeout_seconds:
                await asyncio.sleep(3)
                pages = [p for p in ctx.pages if not p.is_closed()]
                if not pages:
                    break  # user closed the browser
                # Log where the window is (path only, no query string) so a login that
                # isn't detected can be diagnosed from the server log.
                where = ", ".join(sorted({urlsplit(p.url or "").netloc + urlsplit(p.url or "").path
                                          for p in pages}))
                if where != last_seen:
                    log.info("[%s] login window at: %s", platform, where)
                    last_seen = where
                for p in pages:
                    try:
                        if await adapter.is_logged_in(p):
                            # let the site finish setting cookies before closing
                            await asyncio.sleep(3)
                            mark_logged_in(platform)
                            return {"platform": platform, "status": "logged_in",
                                    "email_prefilled": prefilled,
                                    "session_dir": str(session_dir(platform)),
                                    "seconds": int(time.monotonic() - started),
                                    "message": "Login detected and session saved."}
                    except Exception:
                        continue
            return {"platform": platform, "status": "timeout",
                    "session_dir": str(session_dir(platform)),
                    "message": "Login not detected (timed out or window closed). "
                               "Cookies set so far are kept; try again if needed."}
    except Exception as exc:
        log.warning("login for %s failed: %s", platform, exc)
        return {"platform": platform, "status": "error", "message": f"{type(exc).__name__}: {exc}"}
    finally:
        adapter.context = None


async def check_login(platform: str, headless: bool | None = None) -> dict:
    """Open the stored session and verify it is still logged in."""
    adapter = get_adapter(platform)
    try:
        async with open_context(platform, headless=headless) as ctx:
            adapter.context = ctx
            page = await new_page(ctx)
            ok = await adapter.ensure_logged_in(page)
    except Exception as exc:
        return {"platform": platform, "logged_in": False, "error": f"{type(exc).__name__}: {exc}"}
    if not ok:
        clear_login_marker(platform)
    return {"platform": platform, "logged_in": ok}


def session_status() -> dict:
    return {p: session_info(p) for p in SUPPORTED_PLATFORMS}
