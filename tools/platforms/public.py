"""Base for public job boards: searched over plain HTTP, no login, applied to on the site.

Boards like Himalayas and the YC job board publish their listings without an account.
Their jobs come back with ``easy_apply=False``, so the UI offers "Apply on site" (opens
the posting and records it as applied) and bulk apply skips them.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

from .base import SKIPPED, PlatformAdapter, result

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# Location words that mean "anywhere", and Indian cities that mean "India".
ANYWHERE = {"", "remote", "worldwide", "anywhere", "global", "any"}
INDIA_HINTS = ("india", "bengaluru", "bangalore", "gurugram", "gurgaon", "noida", "delhi", "ncr",
               "mumbai", "pune", "hyderabad", "chennai", "kolkata", "ahmedabad", "jaipur", "kochi",
               "chandigarh", "indore", "coimbatore", "remote india")


def wanted_country(location: str | None) -> str | None:
    """The country a search location points to ("India" for Indian cities), or None for anywhere."""
    loc = (location or "").strip().lower()
    if loc in ANYWHERE:
        return None
    if any(h in loc for h in INDIA_HINTS):
        return "India"
    return (location or "").split(",")[-1].strip().title() or None


class PublicBoardAdapter(PlatformAdapter):
    """No login, no browser: search() uses ``http()``, and apply() always defers to the site."""

    login_required = False
    search_requires_login = False
    search_timeout = 60.0

    @asynccontextmanager
    async def http(self) -> AsyncIterator[httpx.AsyncClient]:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9"}
        async with httpx.AsyncClient(headers=headers, timeout=25, follow_redirects=True) as client:
            yield client

    async def is_logged_in(self, page) -> bool:
        return True

    async def ensure_logged_in(self, page) -> bool:
        return True

    async def apply(self, job: dict, profile: dict, dry_run: bool = True) -> dict:
        return result(SKIPPED, f"{self.display_name} jobs are applied to on the company's site. "
                               "Use \"Apply on site\".")

    @property
    def display_name(self) -> str:
        return self.name.title()
