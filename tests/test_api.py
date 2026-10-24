"""Tests for the local web API (api/), the AI features (tools/ai/) and the new
tools/ hooks. No network, no real AI calls, no real config/credentials/DB:
both AI providers are replaced by fake SDK clients, and every test runs
against a throw-away config.json / SQLite DB / data dir.

Run:  .venv\\Scripts\\python -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for _name in ("httpx", "httpx2", "job_mcp", "mcp", "sse_starlette"):
    logging.getLogger(_name).setLevel(logging.ERROR)

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402
from tools import tracker  # noqa: E402
from tools.ai import llm, providers, store  # noqa: E402
from tools.config import invalidate_cache  # noqa: E402
from tools.normalize import normalize_job  # noqa: E402
from tools.platforms import SUPPORTED_PLATFORMS, register  # noqa: E402
from tools.platforms.base import DRY_RUN, PlatformAdapter  # noqa: E402

SECRET = "SECRET-PASSWORD-DO-NOT-LEAK"
BASE_CONFIG = {
    "resume_path": "",
    "name": "Asha Verma", "email": "asha@example.com", "phone": "9000011111",
    "location": "Jaipur, India", "experience_years": 4,
    "credentials": {"naukri": {"email": "login@example.com", "password": SECRET},
                    "indeed": {"email": "x@example.com", "password": SECRET}},
    "custom_top_level": {"keep": True},
    "autofill": {"current_ctc": "12.25", "expected_ctc": "16", "total_experience": "4",
                 "notice_period": "30 days", "gender": "female", "highest_qualification": "B.Tech",
                 "graduation_year": "2021", "primary_cloud": "Azure", "contract_based": "No",
                 "offer_in_hand": "No", "last_working_day": "Currently Working", "date_of_birth": "",
                 "experience": {"python": "4", "langchain": "2", "pytorch": "1"},
                 "preferred_locations": ["Jaipur", "Remote"]},
}
RESUME_LINES = [
    "Asha Verma",
    "asha@example.com | +91 90000 11111 | Jaipur",
    "Summary",
    "Hard-working engineer looking for opportunities.",
    "Experience",
    "ML Engineer, Acme Corp, 2021 - Present",
    "Responsible for building models.",
    "Worked on RAG chatbot using LangChain.",
    "Skills",
    "Python, PyTorch, LangChain, Kubernetes, Rust, Go",
]


def make_docx(lines=RESUME_LINES) -> bytes:
    import docx
    d = docx.Document()
    for ln in lines:
        d.add_paragraph(ln)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def parse_sse(lines) -> list[tuple[str, object]]:
    """[(event, data)] from an iterator of SSE lines; stops after done/error."""
    out, event, data = [], None, []
    for raw in lines:
        line = raw.decode() if isinstance(raw, bytes) else raw
        line = line.rstrip("\r")
        if line == "":
            if event is not None:
                out.append((event, json.loads("\n".join(data)) if data else None))
                if event in ("done", "error"):
                    return out
            event, data = None, []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    return out


# ------------------------------------------------------------- fake AI SDKs

REVIEW_JSON = {
    "sections": [
        {"title": "Header", "lines": [{"id": "L001", "text": "Asha Verma", "kind": "name"},
                                      {"id": "L002", "text": RESUME_LINES[1], "kind": "text"}]},
        {"title": "Summary", "lines": [{"id": "L004", "text": RESUME_LINES[3], "kind": "text"}]},
        {"title": "Experience", "lines": [{"id": "L006", "text": RESUME_LINES[5], "kind": "role"},
                                          {"id": "L007", "text": RESUME_LINES[6], "kind": "bullet"},
                                          {"id": "L008", "text": RESUME_LINES[7], "kind": "bullet"},
                                          {"id": "L999", "text": "invented", "kind": "bullet"}]},
        {"title": "Skills", "lines": [{"id": "L010", "text": RESUME_LINES[9], "kind": "text"}]},
    ],
    "scores": {"accuracy": 70, "ats": 60, "fit": 80, "impact": 50},
    "issues": [
        {"severity": "mistake", "title": "Phone differs from profile", "where": "Header", "why": "Recruiters call it.",
         "before": "+91 90000 11111", "after": "+91 90000 11111", "note": "",
         "gain": {"accuracy": 12, "ats": 0, "fit": 0, "impact": 0}, "line_ids": ["L002", "L999"]},
        {"severity": "change", "title": "Duty, not result", "where": "Experience", "why": "Shows no outcome.",
         "before": RESUME_LINES[6], "after": "Built [N] models that cut [X%] ...", "note": "",
         "gain": {"accuracy": 0, "ats": 4, "fit": 0, "impact": 8}, "line_ids": ["L007"]},
        {"severity": "polish", "title": "Skills bloat", "where": "Skills", "why": "Rust/Go not evidenced.",
         "before": "Rust, Go", "after": "", "note": "Only add this if you've actually used it.",
         "gain": {"accuracy": 0, "ats": 3, "fit": 0, "impact": 0}, "line_ids": ["L010"]},
    ],
}
PREP_JSON = {
    "demand": [{"skill": "Python", "jobs": 90, "you": "strong"}, {"skill": "LangChain", "jobs": 60, "you": "some"},
               {"skill": "Kubernetes", "jobs": 40, "you": "gap"}],
    "plan": [{"week": 1, "text": "Rewrite bullets", "type": "Resume", "time": "Days 1-2", "hours": 3},
             {"week": 2, "text": "Build a RAG eval harness", "type": "Build", "time": "Weekend", "hours": 6}],
    "questions": [{"round": "llm", "q": "How does RAG reduce hallucination?", "why": "Core GenAI topic",
                   "outline": ["retrieval", "grounding", "evals"], "from_resume": "Use the RAG chatbot at Acme."},
                  {"round": "behav", "q": "Tell me about a failure.", "why": "Standard",
                   "outline": ["STAR"], "from_resume": "Acme project"}],
    "note": "Estimated.",
}
FEEDBACK = {"score": 7, "strengths": ["Clear structure"], "improve": ["Quantify impact"]}
COMPARE_JSON = {"summary": "The summary is sharper; dates still overlap.",
                "changes": ["Rewrote the summary", "Fixed the phone number"],
                "previous": [{"n": 1, "outcome": "resolved", "evidence": "Phone now matches."},
                             {"n": 2, "outcome": "partly", "evidence": "Summary names the role."}],
                "new_problems": [3, 99]}


def chat_reply(n_user: int) -> str:
    """Interviewer turns by number of user messages (the hidden context turn counts as 1)."""
    if n_user <= 1:
        return "Hi Asha! Let's begin. How does RAG reduce hallucination?"
    if n_user == 2:
        return "Good. How did you evaluate retrieval quality?"
    if n_user == 3:
        return "And what would you change at 10x scale?"
    return "Thanks, that's all.\n<feedback>" + json.dumps(FEEDBACK) + "</feedback>"


def chunks(text: str, n: int = 7):
    return [text[i:i + n] for i in range(0, len(text), n)]


class Script:
    """Decides the fake model's output for each request; records calls."""

    def __init__(self):
        self.calls: list[dict] = []
        self.structured_overrides: list[str] = []   # raw texts returned first (e.g. invalid JSON)

    def structured(self, name: str) -> str:
        if self.structured_overrides:
            return self.structured_overrides.pop(0)
        return json.dumps({"ReviewOut": REVIEW_JSON, "PrepOut": PREP_JSON, "Feedback": FEEDBACK,
                           "CompareOut": COMPARE_JSON}[name])


class FakeAnthropic:
    """Mimics AsyncAnthropic().beta.messages.stream(...)."""

    def __init__(self, script: Script):
        self.script = script
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw):
        self.script.calls.append({"provider": "anthropic", **kw})
        fmt = (kw.get("output_config") or {}).get("format")
        if fmt:
            text = self.script.structured(fmt["schema"]["title"])
        else:
            text = chat_reply(sum(1 for m in kw["messages"] if m["role"] == "user"))
        script = self.script

        class _Stream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            @property
            def text_stream(self):
                async def gen():
                    for c in chunks(text):
                        yield c
                return gen()

            async def get_final_message(self):
                return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""),
                                                SimpleNamespace(type="text", text=text)],
                                       stop_reason="end_turn", model=kw["model"], script=script)
        return _Stream()


class FakeOpenAI:
    """Mimics AsyncOpenAI().responses.create(...) / .stream(...)."""

    def __init__(self, script: Script):
        self.script = script
        self.responses = SimpleNamespace(create=self._create, stream=self._stream)

    async def _create(self, **kw):
        self.script.calls.append({"provider": "openai", **kw})
        text = self.script.structured(kw["text"]["format"]["name"])
        return SimpleNamespace(output_text=text, status="completed", model=kw["model"], output=[])

    def _stream(self, **kw):
        self.script.calls.append({"provider": "openai", **kw})
        text = chat_reply(sum(1 for m in kw["input"] if m["role"] == "user"))

        class _Stream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def __aiter__(self):
                async def gen():
                    yield SimpleNamespace(type="response.created")
                    for c in chunks(text):
                        yield SimpleNamespace(type="response.output_text.delta", delta=c)
                    yield SimpleNamespace(type="response.completed")
                return gen()

            async def get_final_response(self):
                return SimpleNamespace(output=[], output_text=text, status="completed")
        return _Stream()


# --------------------------------------------------------------- fake sites

class FakeSiteAdapter(PlatformAdapter):
    name = "fakesite"
    login_url = "https://fake.example.com/login"

    async def is_logged_in(self, page):
        return True

    async def ensure_logged_in(self, page):
        return True

    async def search(self, keywords, location, experience_years, limit=40):
        await asyncio.sleep(0.01)
        return [
            {"job_id": "1", "title": "GenAI Engineer", "company": "Acme", "location": "Jaipur",
             "apply_url": "https://fake.example.com/job/1", "skills": ["Python", "LangChain", "RAG"],
             "description": "LLM apps", "exp_min": 2, "exp_max": 6, "posted_days_ago": 1, "easy_apply": True},
            {"job_id": "2", "title": "ML Engineer", "company": "Beta", "location": "Remote",
             "apply_url": "https://fake.example.com/job/2", "skills": ["PyTorch"], "description": "ML",
             "exp_min": 3, "exp_max": 5, "posted_days_ago": 3, "easy_apply": False},
        ]

    async def apply(self, job, profile, dry_run=True):
        return {"status": DRY_RUN, "message": "dry run ok"}


class CaptchaSiteAdapter(FakeSiteAdapter):
    name = "captchasite"

    async def search(self, keywords, location, experience_years, limit=40):
        self.search_issue = "captcha_required"
        return []


# ------------------------------------------------------------------- base

class ApiTestCase(unittest.TestCase):
    """Fresh temp config / DB / data dir per test; fake AI clients optional."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jobmcp_api_"))
        self.cfg = self.tmp / "config.json"
        self.cfg.write_text(json.dumps(BASE_CONFIG, indent=2), encoding="utf-8")
        # JOB_MCP_LOCAL_BASE_URL: a port nothing listens on, so a running LM Studio never counts as configured
        env = {"JOB_MCP_CONFIG": str(self.cfg), "JOB_MCP_DB": str(self.tmp / "app.db"),
               "JOB_MCP_LOCAL_BASE_URL": "http://127.0.0.1:9/v1",
               "JOB_MCP_DATA_DIR": str(self.tmp / "data"), "JOB_MCP_SESSIONS_DIR": str(self.tmp / "sessions"),
               "JOB_MCP_WEB_DIST": str(self.tmp / "no-dist"), "JOB_MCP_NO_DOTENV": "1",
               "JOB_MCP_DELAY_MIN": "0", "JOB_MCP_DELAY_MAX": "0"}
        self._env = mock.patch.dict(os.environ, env)
        self._env.start()
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "JOB_MCP_MODEL",
                  "JOB_MCP_ANTHROPIC_MODEL", "JOB_MCP_OPENAI_MODEL"):
            os.environ.pop(k, None)
        invalidate_cache()
        self.script = Script()
        llm.set_client_factory("anthropic", None)
        llm.set_client_factory("openai", None)
        self._client_cm = TestClient(create_app())
        self.client = self._client_cm.__enter__()

    def tearDown(self):
        self._client_cm.__exit__(None, None, None)
        llm.set_client_factory("anthropic", None)
        llm.set_client_factory("openai", None)
        self._env.stop()
        invalidate_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def use(self, *provider_ids: str):
        for pid in provider_ids:
            fake = FakeAnthropic(self.script) if pid == "anthropic" else FakeOpenAI(self.script)
            llm.set_client_factory(pid, lambda f=fake: f)

    def raw_config(self) -> dict:
        return json.loads(self.cfg.read_text(encoding="utf-8"))

    def events(self, task_id: str) -> list[tuple[str, object]]:
        with self.client.stream("GET", f"/api/tasks/{task_id}/events") as r:
            self.assertEqual(r.status_code, 200)
            self.assertIn("text/event-stream", r.headers["content-type"])
            return parse_sse(r.iter_lines())

    def upload_resume(self, data: bytes | None = None, name: str = "Asha-Verma.docx"):
        return self.client.post("/api/profile/resume", files={"file": (name, data or make_docx(), "application/octet-stream")})

    def analyse(self, role: str = "GenAI Engineer") -> tuple[dict, list]:
        r = self.client.post("/api/resume/analyse", json={"target_role": role})
        self.assertEqual(r.status_code, 200, r.text)
        evs = self.events(r.json()["task_id"])
        self.assertEqual(evs[-1][0], "done", evs[-1])
        return evs[-1][1]["review"], evs


# ------------------------------------------------------------------ tests

class TestHealthAndPlatforms(ApiTestCase):
    def test_health(self):
        h = self.client.get("/api/health").json()
        self.assertTrue(h["ok"])
        self.assertEqual(h["mcp_tools"], 7)
        self.assertEqual(h["ai"], {"configured": False, "provider": "anthropic",
                                   "provider_name": "Claude (Anthropic)", "model": None})
        self.use("anthropic")
        h = self.client.get("/api/health").json()
        self.assertEqual(h["ai"]["configured"], True)
        self.assertEqual(h["ai"]["model"], "claude-opus-5-5")

    def test_platforms(self):
        from tools.browser import mark_logged_in
        mark_logged_in("naukri")
        ps = {p["id"]: p for p in self.client.get("/api/platforms").json()["platforms"]}
        self.assertEqual(set(ps), {"naukri", "instahyre", "indeed", "linkedin", "wellfound", "hirist"})
        self.assertTrue(ps["naukri"]["live"])
        self.assertEqual(ps["naukri"]["session"], "logged_in")
        self.assertIsNotNone(ps["naukri"]["last_checked"])
        self.assertEqual(ps["indeed"]["session"], "not_set_up")
        self.assertFalse(ps["linkedin"]["live"])
        self.assertEqual(self.client.post("/api/platforms/linkedin/check").json()["error"]["code"], "platform_not_live")
        self.assertEqual(self.client.post("/api/platforms/nope/check").status_code, 404)

    def test_unknown_api_and_frontend_note(self):
        r = self.client.get("/api/does-not-exist")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"]["code"], "not_found")
        home = self.client.get("/").text
        self.assertIn("frontend not built", home)
        self.assertIn("cd web &amp;&amp; npm install &amp;&amp; npm run build", home)

    def test_spa_fallback(self):
        dist = self.tmp / "no-dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html>APP</html>", encoding="utf-8")
        (dist / "assets" / "a.js").write_text("console.log(1)", encoding="utf-8")
        self.assertIn("APP", self.client.get("/").text)
        self.assertIn("APP", self.client.get("/resume/prep").text)
        self.assertIn("console.log", self.client.get("/assets/a.js").text)
        self.assertEqual(self.client.get("/api/nope").status_code, 404)


class TestSearch(ApiTestCase):
    def setUp(self):
        super().setUp()
        register("fakesite", "tests.test_api:FakeSiteAdapter")
        register("captchasite", "tests.test_api:CaptchaSiteAdapter")

    def tearDown(self):
        for p in ("fakesite", "captchasite"):
            if p in SUPPORTED_PLATFORMS:
                SUPPORTED_PLATFORMS.remove(p)
        super().tearDown()

    def test_search_events_in_order_and_cache(self):
        r = self.client.post("/api/search", json={"keywords": ["GenAI Engineer"], "location": "India",
                                                  "experience_years": 4, "platforms": ["fakesite", "captchasite"],
                                                  "min_match_score": 0})
        self.assertEqual(r.status_code, 200, r.text)
        evs = self.events(r.json()["task_id"])
        kinds = [e for e, _ in evs]
        self.assertEqual(kinds[-1], "done")
        fake = [d["state"] for e, d in evs if e == "platform" and d["platform"] == "fakesite"]
        self.assertEqual(fake, ["queued", "fetching", "done"])
        cap = [d for e, d in evs if e == "platform" and d["platform"] == "captchasite"]
        self.assertEqual([d["state"] for d in cap], ["queued", "fetching", "failed"])
        self.assertEqual(cap[-1]["reason"], "captcha_required")
        jobs_ev = [i for i, (e, d) in enumerate(evs) if e == "jobs"]
        done_fake = next(i for i, (e, d) in enumerate(evs)
                         if e == "platform" and d["platform"] == "fakesite" and d["state"] == "done")
        self.assertTrue(jobs_ev and jobs_ev[0] < done_fake)
        final = evs[-1][1]
        self.assertEqual(final["total"], 2)
        self.assertEqual(final["shown"], 2)
        j = final["jobs"][0]
        for k in ("platform", "job_id", "title", "company", "location", "salary", "apply_url", "description",
                  "skills", "exp_min", "exp_max", "posted_days_ago", "match_score", "rank_score",
                  "easy_apply", "already_applied"):
            self.assertIn(k, j)
        self.assertGreaterEqual(final["jobs"][0]["rank_score"], final["jobs"][1]["rank_score"])
        snap = self.client.get(f"/api/tasks/{r.json()['task_id']}").json()
        self.assertEqual(snap["status"], "done")
        last = self.client.get("/api/search/last").json()
        self.assertEqual(len(last["jobs"]), 2)
        self.assertEqual(last["params"]["keywords"], ["GenAI Engineer"])
        self.assertIn("https://fake.example.com/job/1", tracker.get_cached_jobs(["https://fake.example.com/job/1"]))

    def test_search_with_exclude_companies(self):
        r = self.client.post("/api/search", json={"keywords": ["GenAI Engineer"], "location": "India",
                                                  "experience_years": 4, "platforms": ["fakesite"],
                                                  "min_match_score": 0, "exclude_companies": ["Acme"]})
        self.assertEqual(r.status_code, 200, r.text)
        evs = self.events(r.json()["task_id"])
        final = evs[-1][1]
        comps = [j["company"] for j in final["jobs"]]
        self.assertNotIn("Acme", comps)
        self.assertIn("Beta", comps)

    def test_search_validation_and_empty_last(self):
        self.assertIsNone(self.client.get("/api/search/last").json())
        r = self.client.post("/api/search", json={"keywords": [], "platforms": ["naukri"]})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/search", json={"keywords": ["ML"], "platforms": ["myspace"]})
        self.assertEqual(r.json()["error"]["detail"]["platforms"][:7], "Unknown")

    def test_search_jobs_hook_directly(self):
        from tools.search import search_jobs
        seen = []
        jobs = asyncio.run(search_jobs(["GenAI"], "India", 4, ["fakesite", "linkedin"], on_platform=seen.append))
        self.assertEqual(len(jobs), 2)
        self.assertIn({"platform": "linkedin", "state": "skipped", "count": 0,
                       "message": "platform not supported yet"}, seen)
        done = [e for e in seen if e["platform"] == "fakesite" and e["state"] == "done"][0]
        self.assertEqual(done["count"], 2)
        self.assertTrue(all("match_score" in j for j in done["jobs"]))


def _cache(*jobs):
    tracker.cache_jobs([normalize_job(j) for j in jobs])


J_DONE = {"platform": "naukri", "job_id": "1", "title": "ML Engineer", "company": "A",
          "apply_url": "https://www.naukri.com/job-listings-done-1", "easy_apply": True}
J_EXT = {"platform": "hirist", "job_id": "2", "title": "AI Engineer", "company": "B",
         "apply_url": "https://www.hirist.tech/j/ext.html", "easy_apply": False}
J_OK1 = {"platform": "naukri", "job_id": "3", "title": "GenAI Engineer", "company": "C",
         "apply_url": "https://www.naukri.com/job-listings-ok-3", "easy_apply": True}
J_OK2 = {"platform": "naukri", "job_id": "4", "title": "LLM Engineer", "company": "D",
         "apply_url": "https://www.naukri.com/job-listings-ok-4", "easy_apply": True}
J_NOSESS = {"platform": "instahyre", "job_id": "5", "title": "ML Engineer", "company": "E",
            "apply_url": "https://www.instahyre.com/job-5/", "easy_apply": True}


class TestApply(ApiTestCase):
    def test_preview(self):
        from tools.browser import mark_logged_in
        _cache(J_DONE, J_EXT, J_OK1, J_OK2, J_NOSESS)
        tracker.record(normalize_job(J_DONE), "applied")
        mark_logged_in("naukri")
        urls = [j["apply_url"] for j in (J_DONE, J_EXT, J_OK1, J_OK2, J_NOSESS)] + ["https://unknown/x"]
        r = self.client.post("/api/apply/preview", json={"apply_urls": urls, "max_applications": 1}).json()
        self.assertEqual([j["apply_url"] for j in r["will_apply"]], [J_OK1["apply_url"]])
        reasons = {s["job"]["apply_url"]: s["reason"] for s in r["will_skip"]}
        self.assertEqual(reasons, {J_DONE["apply_url"]: "already_applied", J_EXT["apply_url"]: "not_easy_apply",
                                   J_OK2["apply_url"]: "over_limit", J_NOSESS["apply_url"]: "session_expired"})
        self.assertTrue(next(s for s in r["will_skip"] if s["reason"] == "already_applied")["job"]["already_applied"])

    def test_confirm_required(self):
        _cache(J_OK1)
        body = {"apply_urls": [J_OK1["apply_url"]], "max_applications": 1, "dry_run": False}
        r = self.client.post("/api/apply", json=body)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "confirm_required")
        r = self.client.post("/api/apply", json={**body, "confirm": "yes"})
        self.assertEqual(r.json()["error"]["code"], "confirm_required")

    def test_unknown_jobs(self):
        r = self.client.post("/api/apply", json={"apply_urls": ["https://nope/1"], "dry_run": True})
        self.assertEqual(r.json()["error"]["code"], "jobs_not_found")

    def test_apply_task_without_browser(self):
        """Only skip paths (already applied / not easy apply): no browser is opened."""
        _cache(J_DONE, J_EXT)
        tracker.record(normalize_job(J_DONE), "applied")
        r = self.client.post("/api/apply", json={"apply_urls": [J_DONE["apply_url"], J_EXT["apply_url"]],
                                                 "max_applications": 5, "dry_run": True})
        evs = self.events(r.json()["task_id"])
        jobs = [d for e, d in evs if e == "job"]
        self.assertEqual([d["state"] for d in jobs], ["skipped", "skipped"])
        prog = [d for e, d in evs if e == "progress"]
        self.assertEqual(prog[-1], {"done": 2, "total": 2})
        done = evs[-1][1]
        self.assertEqual(done["summary"]["already_applied"], 1)
        self.assertEqual(done["summary"]["attempted"], 0)
        self.assertTrue(done["summary"]["dry_run"])

    def test_bulk_apply_hooks_and_cancel(self):
        """on_job states and cancel-after-current-job, with a fake adapter and no browser."""
        from tools import apply as apply_mod
        register("fakesite", "tests.test_api:FakeSiteAdapter")
        cancel = threading.Event()
        seen = []

        def on_job(ev):
            seen.append((ev["apply_url"][-1], ev["state"]))
            if ev["state"] == "dry_run":
                cancel.set()  # cancel during the first job

        @asynccontextmanager
        async def fake_context(platform, headless=None):
            yield SimpleNamespace(pages=[])

        async def fake_page(ctx):
            return SimpleNamespace(url="about:blank")

        jobs = [normalize_job({"platform": "fakesite", "job_id": str(i), "title": f"T{i}", "company": "X",
                               "apply_url": f"https://fake.example.com/apply/{i}", "easy_apply": True})
                for i in (1, 2, 3)]
        try:
            with mock.patch.object(apply_mod, "open_context", fake_context), \
                    mock.patch.object(apply_mod, "new_page", fake_page):
                res = asyncio.run(apply_mod.bulk_apply(jobs, max_applications=3, dry_run=True,
                                                       on_job=on_job, cancel_event=cancel))
        finally:
            SUPPORTED_PLATFORMS.remove("fakesite")
        self.assertTrue(res["summary"]["cancelled"])
        self.assertEqual(res["summary"]["would_apply"], 1)
        self.assertEqual(seen[:3], [("1", "queued"), ("2", "queued"), ("3", "queued")])
        self.assertIn(("1", "applying"), seen)
        self.assertIn(("1", "dry_run"), seen)
        self.assertIn(("2", "skipped"), seen)
        self.assertIn(("3", "skipped"), seen)
        self.assertNotIn(("2", "applying"), seen)
        self.assertEqual([s["reason"] for s in res["skipped"]], ["cancelled", "cancelled"])
        # cancelled jobs are not recorded in the tracker
        self.assertEqual(len(tracker.list_applications()), 1)


class TestApplicationsAndStats(ApiTestCase):
    def test_list_and_stats(self):
        tracker.record(normalize_job(J_OK1), "applied")
        tracker.record(normalize_job(J_OK2), "failed", "Unknown required field")
        tracker.record(normalize_job(J_EXT), "skipped", "not easy apply")
        tracker.record(normalize_job(J_NOSESS), "dry_run")
        apps = self.client.get("/api/applications?status=applied,failed&platform=naukri").json()["applications"]
        self.assertEqual({a["status"] for a in apps}, {"applied", "failed"})
        a = apps[0]
        self.assertEqual(set(a), {"id", "platform", "job_id", "title", "company", "location", "apply_url",
                                  "status", "error", "applied_at"})
        from datetime import datetime
        self.assertIsNotNone(datetime.fromisoformat(a["applied_at"]).tzinfo)  # local time with offset
        self.assertEqual(len(self.client.get("/api/applications").json()["applications"]), 4)
        self.assertEqual(len(self.client.get("/api/applications?days=7&platform=hirist").json()["applications"]), 1)
        s = self.client.get("/api/stats").json()
        self.assertEqual(s["applied_today"], 1)
        self.assertEqual(s["applied_week"], 1)
        self.assertEqual(s["success_rate"], 0.5)
        self.assertEqual(s["by_platform"]["naukri"], {"applied": 1, "failed": 1, "skipped": 0, "dry_run": 0})
        self.assertEqual(len(s["recent"]), 4)


class TestProfile(ApiTestCase):
    def test_get_never_returns_credentials(self):
        r = self.client.get("/api/profile")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("credentials", r.text)
        self.assertNotIn(SECRET, r.text)
        self.assertNotIn("login@example.com", r.text)
        p = r.json()
        self.assertEqual(p["name"], "Asha Verma")
        self.assertIsNone(p["resume"])
        self.assertEqual(p["autofill"]["graduation_year"], "2021")
        self.assertEqual(p["autofill"]["experience"]["python"], "4")

    def test_put_validation(self):
        r = self.client.put("/api/profile", json={
            "email": "not-an-email", "phone": "12345",
            "autofill": {"current_ctc": "twelve", "graduation_year": "1850", "experience": {"python": "lots"}}})
        self.assertEqual(r.status_code, 422)
        err = r.json()["error"]
        self.assertEqual(err["code"], "validation")
        for f in ("email", "phone", "autofill.current_ctc", "autofill.graduation_year", "autofill.experience.python"):
            self.assertIn(f, err["detail"])
        self.assertEqual(self.raw_config(), BASE_CONFIG)  # nothing written

    def test_put_preserves_credentials_and_unknown_keys(self):
        r = self.client.put("/api/profile", json={
            "name": "Asha V", "phone": "+91 98765-43210", "experience_years": 5,
            "credentials": {"naukri": {"password": "hacked"}},
            "autofill": {"expected_ctc": 18.5, "graduation_year": 2021, "offer_in_hand": True,
                         "experience": {"Python": "5", "RAG": 2}, "preferred_locations": ["Pune"]}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn(SECRET, r.text)
        p = r.json()
        self.assertEqual(p["phone"], "9876543210")
        self.assertEqual(p["autofill"]["expected_ctc"], "18.5")
        self.assertEqual(p["autofill"]["offer_in_hand"], "Yes")
        raw = self.raw_config()
        self.assertEqual(raw["credentials"], BASE_CONFIG["credentials"])
        self.assertEqual(raw["custom_top_level"], {"keep": True})
        self.assertEqual(raw["autofill"]["date_of_birth"], "")       # unknown autofill key kept
        self.assertEqual(raw["autofill"]["current_ctc"], "12.25")    # untouched field kept
        self.assertEqual(raw["autofill"]["experience"], {"python": "5", "rag": "2"})
        self.assertEqual(raw["experience_years"], 5)

    def test_resume_upload(self):
        r = self.upload_resume()
        self.assertEqual(r.status_code, 200, r.text)
        info = r.json()
        self.assertEqual(info["filename"], "Asha-Verma.docx")
        self.assertGreater(info["size_bytes"], 0)
        stored = Path(self.raw_config()["resume_path"])
        self.assertTrue(stored.is_file())
        self.assertEqual(stored.parent, (self.tmp / "data" / "resume").resolve())
        self.assertEqual(self.raw_config()["credentials"], BASE_CONFIG["credentials"])
        self.assertEqual(self.client.get("/api/profile").json()["resume"]["filename"], "Asha-Verma.docx")
        r = self.client.post("/api/profile/resume", files={"file": ("cv.txt", b"hello", "text/plain")})
        self.assertEqual(r.status_code, 422)
        big = b"%PDF" + b"0" * (5 * 1024 * 1024)
        r = self.client.post("/api/profile/resume", files={"file": ("cv.pdf", big, "application/pdf")})
        self.assertEqual(r.status_code, 413)


class TestAINotConfigured(ApiTestCase):
    def test_503_everywhere(self):
        self.upload_resume()
        r = self.client.post("/api/resume/analyse", json={"target_role": "GenAI Engineer"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "ai_not_configured")
        r = self.client.post("/api/interview/sessions", json={"question_id": "r1-q1", "role": "GenAI Engineer"})
        self.assertEqual(r.status_code, 503)
        self.assertIsNone(self.client.get("/api/resume/review?role=GenAI%20Engineer").json())

    def test_settings_without_keys(self):
        s = self.client.get("/api/settings/ai").json()
        self.assertEqual(s["provider"], "anthropic")
        self.assertEqual([p["id"] for p in s["providers"]], ["anthropic", "openai", "local"])
        self.assertTrue(all(not p["configured"] for p in s["providers"]))
        self.assertEqual(s["providers"][1]["short"], "ChatGPT")
        r = self.client.put("/api/settings/ai", json={"provider": "openai"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "provider_not_configured")
        self.assertEqual(self.client.put("/api/settings/ai", json={"provider": "gemini"}).status_code, 422)

    def test_env_key_counts_as_configured(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            self.assertEqual(self.client.get("/api/settings/ai").json()["provider"], "openai")

    def test_mcp_offline_context(self):
        import server
        self.upload_resume()
        res = asyncio.run(server.review_resume("GenAI Engineer"))
        self.assertFalse(res["ai_configured"])
        self.assertIn("Worked on RAG chatbot", res["resume"]["text"])
        self.assertEqual(res["profile"]["phone"], "9000011111")
        self.assertNotIn("current_ctc", json.dumps(res))
        self.assertNotIn(SECRET, json.dumps(res))


class TestProviderSwitching(ApiTestCase):
    def test_fallback_and_switch(self):
        self.use("openai")
        self.assertEqual(self.client.get("/api/settings/ai").json()["provider"], "openai")  # only key
        self.assertEqual(self.client.get("/api/health").json()["ai"]["provider_name"], "ChatGPT (OpenAI)")
        self.use("anthropic")
        self.assertEqual(self.client.get("/api/settings/ai").json()["provider"], "anthropic")  # default
        r = self.client.put("/api/settings/ai", json={"provider": "openai"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["provider"], "openai")
        raw = self.raw_config()
        self.assertEqual(raw["ai"], {"provider": "openai"})
        self.assertEqual(raw["credentials"], BASE_CONFIG["credentials"])
        self.assertEqual(raw["custom_top_level"], {"keep": True})
        h = self.client.get("/api/health").json()["ai"]
        self.assertEqual((h["provider"], h["model"]), ("openai", "gpt-6.1-sol"))
        # stored choice loses its key -> falls back to the provider that has one
        llm.set_client_factory("openai", None)
        self.assertEqual(self.client.get("/api/settings/ai").json()["provider"], "anthropic")

    def test_model_env_overrides(self):
        with mock.patch.dict(os.environ, {"JOB_MCP_OPENAI_MODEL": "gpt-6-luna",
                                          "JOB_MCP_ANTHROPIC_MODEL": "claude-sonnet-5-5"}):
            ps = {p["id"]: p["model"] for p in self.client.get("/api/settings/ai").json()["providers"]}
            self.assertEqual(ps, {"anthropic": "claude-sonnet-5-5", "openai": "gpt-6-luna", "local": "local-model"})


class ReviewFlowMixin:
    provider = "anthropic"

    def setUp(self):
        super().setUp()
        self.use(self.provider)
        self.client.put("/api/settings/ai", json={"provider": self.provider})
        self.assertEqual(self.upload_resume().status_code, 200)

    def test_review_flow(self):
        review, evs = self.analyse("GenAI Engineer")
        steps = [d for e, d in evs if e == "step"]
        self.assertEqual([(s["index"], s["state"]) for s in steps],
                         [(0, "running"), (0, "done"), (1, "running"), (1, "done"),
                          (2, "running"), (2, "done"), (3, "running"), (3, "done")])
        self.assertEqual(steps[0]["label"], "Reading Asha-Verma.docx")
        self.assertEqual(steps[4]["label"], "Comparing with 0 matched GenAI Engineer jobs")
        self.assertEqual(review["provider"], self.provider)
        self.assertEqual(review["target_role"], "GenAI Engineer")
        self.assertEqual(review["scores"], REVIEW_JSON["scores"])
        self.assertEqual(review["overall"], 65)
        self.assertEqual(review["projected"], 72)   # (82 + 67 + 80 + 58) / 4 = 71.75
        ids = [ln["id"] for s in review["sections"] for ln in s["lines"]]
        self.assertNotIn("L999", ids)              # invented line dropped
        i1, i2, i3 = review["issues"]
        self.assertEqual(i1["line_ids"], ["L002"])  # unknown id removed from highlights
        self.assertEqual(i1["gain"], {"accuracy": 12})
        self.assertEqual(i1["status"], "open")
        prep = review["prep"]
        self.assertEqual(prep["matched_jobs"], 0)
        self.assertEqual(prep["demand_source"], "estimate")
        self.assertEqual(prep["demand"][0], {"skill": "Python", "jobs": 90, "you": "strong"})
        self.assertEqual(len(prep["plan"]), 2)
        self.assertFalse(prep["plan"][0]["done"])
        self.assertEqual(prep["questions"][0]["from_resume"], "Use the RAG chatbot at Acme.")
        # stored and retrievable by role (case-insensitive)
        got = self.client.get("/api/resume/review?role=genai%20engineer").json()
        self.assertEqual(got["issues"], review["issues"])
        # issue patches recompute overall / projected
        r = self.client.patch(f"/api/resume/issues/{i2['id']}", json={"status": "fixed"}).json()
        self.assertEqual((r["overall"], r["projected"]), (68, 72))   # (70+64+80+58)/4
        self.assertEqual(r["issue"]["status"], "fixed")
        r = self.client.patch(f"/api/resume/issues/{i3['id']}", json={"status": "dismissed"}).json()
        self.assertEqual((r["overall"], r["projected"]), (68, 71))   # (82+64+80+58)/4
        r = self.client.patch(f"/api/resume/issues/{i2['id']}", json={"status": "open"}).json()
        self.assertEqual(r["overall"], 65)
        self.assertEqual(self.client.patch("/api/resume/issues/r9-i9", json={"status": "fixed"}).status_code, 404)
        self.assertEqual(self.client.patch(f"/api/resume/issues/{i2['id']}", json={"status": "x"}).status_code, 422)
        p = self.client.patch(f"/api/resume/plan/{prep['plan'][0]['id']}", json={"done": True}).json()
        self.assertTrue(p["plan_item"]["done"])
        q = self.client.patch(f"/api/resume/questions/{prep['questions'][1]['id']}", json={"practised": True}).json()
        self.assertTrue(q["question"]["practised"])
        got = self.client.get("/api/resume/review?role=GenAI Engineer").json()
        self.assertEqual(got["overall"], 65)
        self.assertEqual(got["projected"], 71)
        self.assertTrue(got["prep"]["plan"][0]["done"])
        # the cached resume prefix is identical in both analysis calls
        calls = [c for c in self.script.calls if c["provider"] == self.provider]
        self.assertEqual(len(calls), 2)
        return calls

    def test_interview_flow(self):
        review, _ = self.analyse("GenAI Engineer")
        qid = review["prep"]["questions"][0]["id"]
        r = self.client.post("/api/interview/sessions", json={"question_id": qid, "role": "GenAI Engineer"})
        self.assertEqual(r.status_code, 200, r.text)
        sid = r.json()["session_id"]
        self.assertEqual(r.json()["messages"], [{"role": "assistant", "content": chat_reply(1)}])
        for n, answer in enumerate(["Retrieval grounds answers.", "Recall@k and human evals.", "Shard the index."],
                                   start=2):
            with self.client.stream("POST", f"/api/interview/sessions/{sid}/messages",
                                    json={"content": answer}) as resp:
                self.assertEqual(resp.status_code, 200)
                evs = parse_sse(resp.iter_lines())
            deltas = "".join(d["text"] for e, d in evs if e == "delta")
            self.assertNotIn("<feedback", deltas)
            self.assertNotIn("{", deltas)
            done = evs[-1]
            self.assertEqual(done[0], "done")
            self.assertEqual(done[1]["message"]["content"], deltas.strip())
            if n < 4:
                self.assertNotIn("feedback", done[1])
            else:
                self.assertEqual(done[1]["feedback"], FEEDBACK)
                self.assertEqual(deltas.strip(), "Thanks, that's all.")
        sess = self.client.get(f"/api/interview/sessions/{sid}").json()
        self.assertEqual(sess["feedback"], FEEDBACK)
        self.assertEqual(len(sess["messages"]), 7)
        got = self.client.get("/api/resume/review?role=GenAI Engineer").json()
        self.assertTrue(got["prep"]["questions"][0]["practised"])
        r = self.client.post(f"/api/interview/sessions/{sid}/messages", json={"content": "more?"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.get("/api/interview/sessions/nope").status_code, 404)


class TestReviewAnthropic(ReviewFlowMixin, ApiTestCase):
    provider = "anthropic"

    def test_review_flow(self):
        calls = super().test_review_flow()
        for c in calls:
            self.assertEqual(c["model"], "claude-opus-5-5")
            self.assertEqual(c["output_config"]["effort"], "high")
            self.assertEqual(c["output_config"]["format"]["type"], "json_schema")
            self.assertEqual(c["fallbacks"], "default")
            first = c["messages"][0]["content"][0]
            self.assertEqual(first["cache_control"], {"type": "ephemeral"})
            self.assertIn("L008: Worked on RAG chatbot using LangChain.", first["text"])
            self.assertNotIn("12.25", first["text"])   # CTC is not sent
        self.assertEqual(calls[0]["messages"][0]["content"][0], calls[1]["messages"][0]["content"][0])

    def test_retry_once_then_fail(self):
        self.script.structured_overrides = ["{not json", json.dumps({"sections": []})]
        r = self.client.post("/api/resume/analyse", json={"target_role": "GenAI Engineer"})
        evs = self.events(r.json()["task_id"])
        self.assertEqual(evs[-1][0], "error")
        self.assertEqual(evs[-1][1]["code"], "ai_invalid_output")
        snap = self.client.get(f"/api/tasks/{r.json()['task_id']}").json()
        self.assertEqual(snap["status"], "error")

    def test_retry_once_then_succeed(self):
        self.script.structured_overrides = ["{not json"]
        review, _ = self.analyse()
        self.assertEqual(review["overall"], 65)
        self.assertEqual(len(self.script.calls), 3)   # review x2 + prep


class TestReviewOpenAI(ReviewFlowMixin, ApiTestCase):
    provider = "openai"

    def test_review_flow(self):
        calls = super().test_review_flow()
        for c in calls:
            self.assertEqual(c["model"], "gpt-6.1-sol")
            fmt = c["text"]["format"]
            self.assertEqual((fmt["type"], fmt["strict"]), ("json_schema", True))
            self.assertFalse(fmt["schema"]["additionalProperties"])
            self.assertNotIn("maximum", json.dumps(fmt["schema"]))
            self.assertEqual(c["reasoning"], {"effort": "medium"})
            self.assertIn("never invent", c["instructions"].lower())
            self.assertIn("L008: Worked on RAG chatbot", c["input"][0]["content"])

    def test_demand_from_cached_jobs(self):
        jobs = [{"platform": "naukri", "job_id": str(i), "title": "GenAI Engineer", "company": f"C{i}",
                 "apply_url": f"https://www.naukri.com/job-listings-g-{i}",
                 "skills": ["Python", "LangChain", "Kubernetes"] if i < 4 else ["Python"],
                 "description": "Build RAG apps"} for i in range(6)]
        jobs.append({"platform": "naukri", "job_id": "x", "title": "Java Developer", "company": "J",
                     "apply_url": "https://www.naukri.com/job-listings-java", "skills": ["Java"]})
        _cache(*jobs)
        review, evs = self.analyse("GenAI Engineer")
        self.assertEqual([d for e, d in evs if e == "step"][4]["label"], "Comparing with 6 matched GenAI Engineer jobs")
        prep = review["prep"]
        self.assertEqual((prep["matched_jobs"], prep["demand_source"], prep["demand_scale"]), (6, "jobs", 6))
        rows = {r["skill"]: r for r in prep["demand"]}
        self.assertEqual(rows["Python"]["jobs"], 6)
        self.assertEqual(rows["RAG"]["jobs"], 6)
        self.assertEqual(rows["LangChain"], {"skill": "LangChain", "jobs": 4, "you": "some"})
        self.assertEqual(rows["Kubernetes"]["you"], "gap")
        self.assertNotIn("Java", rows)


class TestScoresAndStore(unittest.TestCase):
    def test_compute_scores_caps_at_100(self):
        base = {"accuracy": 95, "ats": 50, "fit": 50, "impact": 50}
        issues = [{"status": "fixed", "gain": {"accuracy": 10}}, {"status": "open", "gain": {"ats": 8}},
                  {"status": "dismissed", "gain": {"fit": 40}}]
        self.assertEqual(store.compute_scores(base, issues), (63, 65))   # 62.5 and 64.5, rounded half up


class TestInterviewParsing(unittest.TestCase):
    def test_feedback_parse_and_partial_tag(self):
        from tools.ai.interview import _partial_tag_len, parse_feedback
        visible, fb = parse_feedback('Done.\n<feedback>{"score": 12, "strengths": ["a"], "improve": ["b"]}</feedback>')
        self.assertEqual(visible, "Done.")
        self.assertEqual(fb.score, 10)
        self.assertEqual(parse_feedback("Next question?"), ("Next question?", None))
        self.assertEqual(_partial_tag_len("hello <feed"), 5)
        self.assertEqual(_partial_tag_len("hello"), 0)


@unittest.skipUnless(os.environ.get("JOB_MCP_SKIP_BROWSER_TEST", "") != "1", "browser test disabled")
class TestBrowserFromApi(ApiTestCase):
    def test_headless_chromium_launches_from_request(self):
        r = self.client.get("/api/diagnostics/browser").json()
        if not r["ok"] and "Executable doesn't exist" in r.get("error", ""):
            self.skipTest("Playwright Chromium not installed")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["url"], "about:blank")
        if sys.platform == "win32":
            self.assertEqual(r["loop"], "ProactorEventLoop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
