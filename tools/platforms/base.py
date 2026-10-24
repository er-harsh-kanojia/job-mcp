"""Abstract platform adapter.

An adapter either owns a browser context for one call (when constructed with
``context=None``) or reuses a context handed to it (bulk_apply opens one context
per platform and applies to many jobs with it).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import AsyncIterator

from ..browser import open_context, new_page, wait_for_human_challenge

APPLIED = "applied"
DRY_RUN = "dry_run"
FAILED = "failed"
SKIPPED = "skipped"


def result(status: str, message: str = "", **extra) -> dict:
    """Standard apply() result."""
    out = {"status": status, "error" if status in (FAILED, SKIPPED) else "message": message}
    out.update(extra)
    return out


class NotLoggedIn(RuntimeError):
    pass


class PlatformAdapter(ABC):
    #: registry key, e.g. "naukri"
    name: str = ""
    #: page used by interactive_login
    login_url: str = ""
    #: page that shows whether we are logged in (navigated to by ensure_logged_in)
    home_url: str = ""
    #: CSS selectors of the e-mail field on the login page (for prefill only)
    login_email_selectors: list[str] = []
    #: seconds allowed for one search() call before the aggregator gives up
    search_timeout: float = 90.0
    #: whether search() needs a logged-in session
    search_requires_login: bool = False

    def __init__(self, context=None):
        self.context = context
        #: set by search() when it had to give up early for a known reason
        #: ("captcha_required" / "session_expired"); read by tools.search
        self.search_issue: str | None = None
        self.log = logging.getLogger(f"job_mcp.{self.name or 'platform'}")

    # ------------------------------------------------------------ contexts
    @asynccontextmanager
    async def browser(self) -> AsyncIterator:
        """Yield a browser context: the bound one, or a fresh persistent one."""
        if self.context is not None:
            yield self.context
        else:
            async with open_context(self.name) as ctx:
                self.context = ctx
                try:
                    yield ctx
                finally:
                    self.context = None

    async def page(self):
        if self.context is None:
            raise RuntimeError("No browser context bound")
        return await new_page(self.context)

    # ------------------------------------------------------------ interface
    @abstractmethod
    async def is_logged_in(self, page) -> bool:
        """Check login state on the *current* page without navigating."""

    async def ensure_logged_in(self, page) -> bool:
        """Navigate to the home page if needed, then check login state."""
        from urllib.parse import urlsplit
        if self.home_url and urlsplit(page.url).netloc != urlsplit(self.home_url).netloc:
            try:
                await page.goto(self.home_url, wait_until="domcontentloaded", timeout=45_000)
            except Exception as exc:
                self.log.warning("%s: could not open home page: %s", self.name, exc)
        # A bot check here is not "logged out": let the user solve it (headed,
        # interactive runs only) before deciding.
        await wait_for_human_challenge(page, self.name)
        return await self.is_logged_in(page)

    @abstractmethod
    async def search(self, keywords: list[str], location: str, experience_years: int,
                     limit: int = 40) -> list[dict]:
        """Return raw-ish job dicts (they are normalised by tools.search)."""

    @abstractmethod
    async def apply(self, job: dict, profile: dict, dry_run: bool = True) -> dict:
        """Apply to one job. Must never click a final submit when dry_run=True.

        Returns {"status": applied|dry_run|failed|skipped, "message"/"error": str, ...}
        """
