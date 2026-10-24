"""Tests for bot-challenge detection (tools.browser.is_challenge) and the
non-interactive fail-soft path. No browser is launched."""

import asyncio
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.browser import (CAPTCHA_REQUIRED, captcha_hint, interactive_allowed,  # noqa: E402
                           is_challenge, wait_for_human_challenge)

CLOUDFLARE_INTERSTITIAL = """<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>
<meta http-equiv="refresh" content="390"></head><body><div class="main-wrapper" role="main">
<h1 class="zone-name-title h1">in.indeed.com</h1><h2 id="challenge-running">Verifying you are human.
This may take a few seconds.</h2><script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1?ray=8f"></script>
</div></body></html>"""

INDEED_BLOCK_PAGE = """<html><head><title>in.indeed.com</title></head><body>
<nav>Find jobs Company Reviews Find salaries</nav><h1>Additional Verification Required</h1>
<p>Your Ray ID for this request is a44b59b1bda9a7f7</p><a>Troubleshooting Cloudflare Errors</a></body></html>"""

TURNSTILE_WIDGET = """<html><head><title>Indeed</title></head><body><h2>Verify you are human by completing
the action below.</h2><iframe src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/turnstile/if/ov2"></iframe>
</body></html>"""

NORMAL_RESULTS = """<html><head><title>Ml Engineer Jobs, Employment | Indeed</title></head><body>
<div class="job_seen_beacon"><h2 class="jobTitle"><a data-jk="abc">Machine Learning Engineer</a></h2>
<span data-testid="company-name">Acme</span><p>Just a moment of your time: we value human-centred design.</p>
<p>Cloudflare experience is a plus.</p></div></body></html>"""


class _FakeLocator:
    def __init__(self, text):
        self._text = text

    async def inner_text(self, timeout=None):
        return self._text


class _FakeFrame:
    def __init__(self, url):
        self.url = url


class _FakePage:
    def __init__(self, title, text, url="https://in.indeed.com/jobs?q=ml", frames=()):
        self._title, self._text, self.url = title, text, url
        self.frames = [_FakeFrame(u) for u in frames]

    async def title(self):
        return self._title

    def locator(self, sel):
        return _FakeLocator(self._text)

    def is_closed(self):
        return False


class TestChallengeDetection(unittest.TestCase):
    def test_cloudflare_interstitial(self):
        self.assertTrue(is_challenge(CLOUDFLARE_INTERSTITIAL, "Just a moment...", "https://in.indeed.com/jobs"))
        self.assertTrue(is_challenge(CLOUDFLARE_INTERSTITIAL))  # markup alone

    def test_additional_verification_page(self):
        self.assertTrue(is_challenge(INDEED_BLOCK_PAGE))

    def test_turnstile_iframe(self):
        self.assertTrue(is_challenge(TURNSTILE_WIDGET, "Indeed"))

    def test_cf_chl_url(self):
        self.assertTrue(is_challenge("", "", "https://in.indeed.com/jobs?q=ml&__cf_chl_rt_tk=abc"))
        self.assertTrue(is_challenge("", "", "https://www.example.com/?cf-chl=1"))

    def test_normal_page_not_flagged(self):
        # "Just a moment" / "Cloudflare" in ordinary body text must not trigger.
        self.assertFalse(is_challenge(NORMAL_RESULTS, "Ml Engineer Jobs, Employment | Indeed",
                                      "https://in.indeed.com/jobs?q=ml"))
        self.assertFalse(is_challenge("", "", ""))


class TestNonInteractiveFailSoft(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("JOB_MCP_NONINTERACTIVE")
        os.environ["JOB_MCP_NONINTERACTIVE"] = "1"

    def tearDown(self):
        if self._old is None:
            os.environ.pop("JOB_MCP_NONINTERACTIVE", None)
        else:
            os.environ["JOB_MCP_NONINTERACTIVE"] = self._old

    def test_returns_false_immediately_on_challenge(self):
        self.assertFalse(interactive_allowed())
        page = _FakePage("Just a moment...", "Additional Verification Required")
        self.assertFalse(asyncio.run(asyncio.wait_for(
            wait_for_human_challenge(page, "indeed", timeout=120), timeout=5)))

    def test_detected_via_iframe_url(self):
        page = _FakePage("Indeed", "Find jobs", frames=["https://challenges.cloudflare.com/turnstile/x"])
        self.assertFalse(asyncio.run(wait_for_human_challenge(page, "indeed")))

    def test_clear_page_passes(self):
        page = _FakePage("Ml Engineer Jobs | Indeed", "Machine Learning Engineer Acme")
        self.assertTrue(asyncio.run(wait_for_human_challenge(page, "indeed")))

    def test_hint_and_constant(self):
        self.assertEqual(CAPTCHA_REQUIRED, "captcha_required")
        self.assertIn("python run.py", captcha_hint("indeed"))

    def test_indeed_apply_fails_soft_with_captcha_required(self):
        from tools.platforms.indeed import IndeedAdapter

        class _Ctx:
            pages = []

        class _Page(_FakePage):
            context = _Ctx()

            async def goto(self, *a, **k):
                return None

        adapter = IndeedAdapter(context=_Ctx())
        page = _Page("Just a moment...", "Verify you are human")

        async def run():
            import tools.platforms.indeed as ind
            orig = ind.human_pause

            async def no_pause(*a, **k):
                return None
            ind.human_pause = no_pause
            try:
                return await adapter._apply(_Ctx(), page, {"apply_url": "https://in.indeed.com/viewjob?jk=x",
                                                           "easy_apply": True}, {}, True)
            finally:
                ind.human_pause = orig
        res = asyncio.run(run())
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["error"], "captcha_required")
        self.assertIn("run.py", res["hint"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
