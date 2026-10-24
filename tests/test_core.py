"""Smoke tests for normalisation, scoring, dedupe, filtering, autofill, parsers and tracker.

Run:  .venv\\Scripts\\python -m unittest discover -s tests -v
No network, no browser, no real config/credentials are used.
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolate from the real config.json and DB before importing tools.
_TMP = tempfile.mkdtemp(prefix="jobmcp_test_")
FAKE_CONFIG = {
    "name": "Test User", "email": "test@example.com", "phone": "+91 90000 00000",
    "location": "Jaipur, India", "experience_years": 4, "resume_path": "",
    "credentials": {"naukri": {"email": "login@example.com", "password": "SECRET-DO-NOT-LEAK"}},
    "autofill": {
        "current_ctc": "12.25", "expected_ctc": "16", "total_experience": "4",
        "notice_period": "30 days", "gender": "male", "highest_qualification": "B.Tech",
        "graduation_year": "2022", "primary_cloud": "Azure", "contract_based": "No",
        "offer_in_hand": "No", "last_working_day": "Currently Working",
        "experience": {"python": "4", "machine learning": "4", "deep learning": "3", "nlp": "4",
                       "generative ai": "4", "llm": "4", "langchain": "2", "pytorch": "1",
                       "scikit-learn": "3", "computer vision": "3"},
        "preferred_locations": ["Delhi NCR", "Gurugram", "Hyderabad", "Jaipur", "Remote", "Bengaluru"],
    },
}
_cfg_path = Path(_TMP) / "config.json"
_cfg_path.write_text(json.dumps(FAKE_CONFIG), encoding="utf-8")
os.environ["JOB_MCP_CONFIG"] = str(_cfg_path)
os.environ["JOB_MCP_DB"] = str(Path(_TMP) / "test_applications.db")

from tools import config, tracker  # noqa: E402
from tools.autofill import answer_question, find_skill  # noqa: E402
from tools.normalize import (OPEN_ENDED, canonical_url, dedupe_jobs, normalize_job,  # noqa: E402
                             parse_experience, parse_posted_days)
from tools.platforms import PLANNED_PLATFORMS, SUPPORTED_PLATFORMS, get_adapter_class  # noqa: E402
from tools.platforms import indeed, instahyre, naukri  # noqa: E402
from tools.scoring import (compute_match_score, compute_rank_score, experience_incompatible,  # noqa: E402
                           recency_score)
from tools.search import filter_jobs, is_company_excluded, score_jobs  # noqa: E402

PROFILE_SKILLS = list(FAKE_CONFIG["autofill"]["experience"])
PREFS = FAKE_CONFIG["autofill"]["preferred_locations"]


def job(**kw):
    base = {"platform": "naukri", "job_id": "1", "title": "ML Engineer", "company": "Acme",
            "location": "Bengaluru", "apply_url": "https://www.naukri.com/job-listings-x-1",
            "description": "Python, machine learning, NLP, LLM", "skills": ["Python", "NLP"],
            "exp_min": 3, "exp_max": 6, "posted_days_ago": 2, "easy_apply": True}
    base.update(kw)
    return normalize_job(base)


class TestNormalize(unittest.TestCase):
    def test_parse_experience(self):
        self.assertEqual(parse_experience("3-8 Yrs"), (3, 8))
        self.assertEqual(parse_experience("2 to 4 years"), (2, 4))
        self.assertEqual(parse_experience("5+ years of experience"), (5, OPEN_ENDED))
        self.assertEqual(parse_experience("minimum 3 years"), (3, OPEN_ENDED))
        self.assertEqual(parse_experience("Fresher"), (0, 1))
        self.assertEqual(parse_experience(""), (-1, -1))
        self.assertEqual(parse_experience("great team"), (-1, -1))

    def test_parse_posted_days(self):
        self.assertEqual(parse_posted_days("3 Days Ago"), 3)
        self.assertEqual(parse_posted_days("Just posted"), 0)
        self.assertEqual(parse_posted_days("Today"), 0)
        self.assertEqual(parse_posted_days("30+ days ago"), 30)
        self.assertEqual(parse_posted_days("2 weeks ago"), 14)
        self.assertEqual(parse_posted_days("Few Hours Ago"), 0)
        self.assertEqual(parse_posted_days(None), -1)

    def test_normalize_defaults_and_types(self):
        j = normalize_job({"title": " <b>AI Engineer</b> ", "apply_url": "u", "exp_min": "5",
                           "skills": "python, nlp | llm", "salary": None}, "Indeed")
        self.assertEqual(j["platform"], "indeed")
        self.assertEqual(j["title"], "AI Engineer")
        self.assertEqual(j["salary"], "Not disclosed")
        self.assertEqual(j["skills"], ["python", "nlp", "llm"])
        self.assertEqual((j["exp_min"], j["exp_max"]), (5, OPEN_ENDED))
        self.assertEqual(j["posted_days_ago"], -1)
        self.assertEqual(j["company"], "Unknown")
        for key in ("platform", "job_id", "title", "company", "location", "salary", "apply_url",
                    "description", "skills", "exp_min", "exp_max", "posted_days_ago",
                    "match_score", "rank_score", "easy_apply"):
            self.assertIn(key, j)

    def test_canonical_url(self):
        self.assertEqual(canonical_url("https://In.Indeed.com/viewjob?jk=abc&from=serp&vjs=3#x"),
                         "https://in.indeed.com/viewjob?jk=abc")
        self.assertEqual(canonical_url("https://www.naukri.com/job-listings-a-1/?src=jobsearchDesk"),
                         "https://www.naukri.com/job-listings-a-1")


class TestDedupe(unittest.TestCase):
    def test_dedupe_by_url_and_title_company(self):
        a = job(apply_url="https://www.naukri.com/job-1", rank_score=0.5)
        a_dup = job(apply_url="https://www.naukri.com/job-1/?src=x", rank_score=0.4)
        b = job(platform="indeed", apply_url="https://in.indeed.com/viewjob?jk=1",
                title="Sr. ML Engineer", company="Acme Pvt Ltd", easy_apply=False, rank_score=0.9)
        b_naukri = job(apply_url="https://www.naukri.com/job-2", title="Senior ML Engineer",
                       company="ACME Private Limited", easy_apply=True, rank_score=0.3)
        other = job(apply_url="https://www.naukri.com/job-3", title="Data Engineer", company="Beta")
        out = dedupe_jobs([a, a_dup, b, b_naukri, other])
        urls = [j["apply_url"] for j in out]
        self.assertEqual(len(out), 3, urls)
        # easy-apply copy wins over the non-easy one with higher rank
        self.assertIn("https://www.naukri.com/job-2", urls)
        self.assertNotIn("https://in.indeed.com/viewjob?jk=1", urls)
        self.assertIn("https://www.naukri.com/job-1", urls)

    def test_same_platform_same_title_kept(self):
        x = job(apply_url="https://www.instahyre.com/job-1/", platform="instahyre", location="Pune")
        y = job(apply_url="https://www.instahyre.com/job-2/", platform="instahyre", location="Noida")
        z = job(apply_url="https://www.naukri.com/job-9", platform="naukri")
        out = dedupe_jobs([x, y, z])
        self.assertEqual([j["apply_url"] for j in out],
                         ["https://www.instahyre.com/job-1/", "https://www.instahyre.com/job-2/"])

    def test_unknown_company_not_merged(self):
        x = job(apply_url="u1", company="")
        y = job(apply_url="u2", company="")
        self.assertEqual(len(dedupe_jobs([x, y])), 2)


class TestScoring(unittest.TestCase):
    def test_good_match_beats_poor_match(self):
        good = job(title="Machine Learning Engineer", skills=["Python", "LLM", "NLP"],
                   location="Gurgaon", exp_min=3, exp_max=6)
        poor = job(title="Java Backend Developer", skills=["Java", "Spring"], description="Java microservices",
                   location="Chennai", exp_min=8, exp_max=12)
        gs = compute_match_score(good, ["ML Engineer"], 4, PROFILE_SKILLS, PREFS)
        ps = compute_match_score(poor, ["ML Engineer"], 4, PROFILE_SKILLS, PREFS)
        self.assertGreater(gs, 0.8)
        self.assertLess(ps, 0.25)
        self.assertTrue(0 <= ps <= gs <= 1)

    def test_abbreviation_synonyms(self):
        j = job(title="AI/ML Engineer - Generative AI")
        self.assertGreater(compute_match_score(j, ["GenAI Engineer"], 4, PROFILE_SKILLS, PREFS),
                           compute_match_score(job(title="QA Engineer", skills=[], description=""),
                                               ["GenAI Engineer"], 4, PROFILE_SKILLS, PREFS))

    def test_recency_and_rank(self):
        self.assertEqual(recency_score(0), 1.0)
        self.assertEqual(recency_score(-1), 0.4)
        self.assertEqual(recency_score(100), 0.05)
        self.assertGreater(compute_rank_score(0.8, 1), compute_rank_score(0.8, 25))
        self.assertAlmostEqual(compute_rank_score(1.0, 0), 1.0)

    def test_experience_incompatible(self):
        self.assertTrue(experience_incompatible(job(exp_min=8, exp_max=12), 4))
        self.assertFalse(experience_incompatible(job(exp_min=6, exp_max=10), 4))
        self.assertTrue(experience_incompatible(job(exp_min=0, exp_max=1), 6))
        self.assertFalse(experience_incompatible(job(exp_min=-1, exp_max=-1), 4))
        self.assertFalse(experience_incompatible(job(exp_min=3, exp_max=OPEN_ENDED), 4))

    def test_score_and_filter_pipeline(self):
        jobs = [
            job(apply_url="a", title="LLM Engineer", posted_days_ago=1),
            job(apply_url="b", title="ML Engineer", company="Old Co", posted_days_ago=29),
            job(apply_url="c", title="Principal ML Engineer", company="Senior Co", exp_min=10, exp_max=15),
            job(apply_url="d", title="Sales Executive", company="Shop", skills=["Sales"],
                description="field sales", location="Chennai"),
        ]
        score_jobs(jobs, ["ML Engineer", "LLM Engineer"], 4, PROFILE_SKILLS, PREFS)
        out = filter_jobs(jobs, min_match_score=0.25, experience_years=4)
        urls = [j["apply_url"] for j in out]
        self.assertNotIn("c", urls)  # experience-incompatible
        self.assertNotIn("d", urls)  # low match
        self.assertEqual(urls[0], "a")  # fresher posting ranks first
        ranks = [j["rank_score"] for j in out]
        self.assertEqual(ranks, sorted(ranks, reverse=True))
        for j in out:
            self.assertTrue(0 <= j["match_score"] <= 1 and 0 <= j["rank_score"] <= 1)

    def test_exclude_companies(self):
        self.assertTrue(is_company_excluded("Tata Consultancy Services", ["TCS", "Tata Consultancy"]))
        self.assertTrue(is_company_excluded("Infosys Ltd", ["infosys"]))
        self.assertFalse(is_company_excluded("Google", ["TCS", "Infosys"]))
        self.assertFalse(is_company_excluded("", ["TCS"]))
        self.assertFalse(is_company_excluded("Google", []))

        jobs = [
            job(apply_url="a", title="ML Engineer", company="Acme Corp"),
            job(apply_url="b", title="ML Engineer", company="ExcludeMe Inc"),
            job(apply_url="c", title="ML Engineer", company="Good Corp"),
        ]
        score_jobs(jobs, ["ML Engineer"], 4, PROFILE_SKILLS, PREFS)
        out = filter_jobs(jobs, min_match_score=0.25, experience_years=4, exclude_companies=["excludeme"])
        urls = [j["apply_url"] for j in out]
        self.assertIn("a", urls)
        self.assertNotIn("b", urls)
        self.assertIn("c", urls)


class TestAutofill(unittest.TestCase):
    def setUp(self):
        self.p = config.get_profile()

    def test_profile_has_no_credentials(self):
        self.assertNotIn("credentials", self.p)
        self.assertNotIn("SECRET-DO-NOT-LEAK", json.dumps(self.p))
        self.assertEqual(config.get_login_email("naukri"), "login@example.com")

    def test_ctc_and_notice(self):
        self.assertEqual(answer_question("What is your current CTC (in Lakhs)?", self.p), "12.25")
        self.assertEqual(answer_question("Expected CTC?", self.p), "16")
        self.assertEqual(answer_question("Current CTC in rupees", self.p, kind="number"), "1225000")
        self.assertEqual(answer_question("What is your notice period?", self.p), "30 days")
        self.assertEqual(answer_question("Notice period (days)", self.p, kind="number"), "30")
        opts = ["15 Days or less", "1 Month", "2 Months", "3 Months"]
        self.assertEqual(answer_question("Notice period", self.p, kind="radio", options=opts), "1 Month")

    def test_skill_experience(self):
        sk = {k: v for k, v in FAKE_CONFIG["autofill"]["experience"].items()}
        self.assertEqual(find_skill("How many years of experience in Gen AI?", sk), "generative ai")
        self.assertEqual(answer_question("Years of experience in PyTorch?", self.p), "1")
        self.assertEqual(answer_question("How many years of experience do you have in Langchian?", self.p), "2")
        self.assertEqual(answer_question("Total years of experience", self.p), "4")
        # unknown skill: do not guess
        self.assertIsNone(answer_question("How many years of experience in Kubernetes?", self.p))
        self.assertEqual(answer_question("Do you have experience in Python?", self.p, kind="radio",
                                         options=["Yes", "No"]), "Yes")

    def test_location_and_yes_no(self):
        self.assertEqual(answer_question("Current location", self.p), "Jaipur")
        self.assertEqual(answer_question("Are you willing to relocate?", self.p, kind="radio",
                                         options=["Yes", "No"]), "Yes")
        self.assertEqual(answer_question("Will you require visa sponsorship?", self.p), "No")
        self.assertEqual(answer_question("Graduation year", self.p), "2022")
        self.assertIsNone(answer_question("What is your favourite colour?", self.p))


class TestParsers(unittest.TestCase):
    def test_naukri_api_job(self):
        raw = {"jobId": "031025012345", "title": "GenAI Engineer", "companyName": "Acme",
               "jdURL": "/job-listings-genai-engineer-acme-bengaluru-3-to-6-years-031025012345",
               "placeholders": [{"type": "experience", "label": "3-6 Yrs"},
                                {"type": "salary", "label": "Not disclosed"},
                                {"type": "location", "label": "Bengaluru, Hyderabad"}],
               "tagsAndSkills": "Python,LLM,RAG", "footerPlaceholderLabel": "2 Days Ago",
               "jobDescription": "<p>Build <b>LLM</b> apps</p>"}
        j = normalize_job(naukri.parse_api_job(raw))
        self.assertEqual(j["apply_url"], "https://www.naukri.com/job-listings-genai-engineer-acme-bengaluru-3-to-6-years-031025012345")
        self.assertEqual((j["exp_min"], j["exp_max"], j["posted_days_ago"]), (3, 6, 2))
        self.assertEqual(j["skills"], ["Python", "LLM", "RAG"])
        self.assertEqual(j["salary"], "Not disclosed")
        self.assertEqual(j["description"], "Build LLM apps")
        self.assertTrue(j["easy_apply"])
        ext = naukri.parse_api_job(dict(raw, companyApplyUrl="https://acme.example/jobs/1"))
        self.assertFalse(ext["easy_apply"])

    def test_naukri_url(self):
        url = naukri.build_search_url(["ML Engineer"], "India", 4)
        self.assertEqual(url, "https://www.naukri.com/ml-engineer-jobs-in-india?k=ML%20Engineer&l=india&experience=4")
        self.assertIn("-in-india-2?", naukri.build_search_url(["ML Engineer"], "India", 4, 2))

    def test_instahyre(self):
        o = {"id": 445475, "title": "LLM Engineer", "employer": {"company_name": "Tekion"},
             "locations": "Bangalore,Hyderabad", "keywords": ["LLMs", "Python"],
             "public_url": "https://www.instahyre.com/job-445475-llm-engineer-at-tekion-bangalore/"}
        j = instahyre.parse_search_object(o)
        j = instahyre.merge_detail(j, {"workex_min": 3, "workex_max": 6, "is_active": True,
                                       "description": "<p>Do things</p>", "locations": ["Bangalore", "Hyderabad"]})
        j = normalize_job(j)
        self.assertEqual((j["job_id"], j["company"], j["exp_min"], j["exp_max"]), ("445475", "Tekion", 3, 6))
        self.assertEqual(j["location"], "Bangalore, Hyderabad")
        self.assertIsNone(instahyre.merge_detail(dict(j), {"is_active": False}))

    def test_indeed(self):
        r = {"jobkey": "abc123", "displayTitle": "Machine Learning Engineer", "company": "Beta",
             "formattedLocation": "Gurugram, Haryana", "snippet": "<li>3+ years in Python</li>",
             "formattedRelativeTime": "5 days ago", "indeedApplyEnabled": True,
             "salarySnippet": {"text": "₹10,00,000 - ₹20,00,000 a year"}}
        j = normalize_job(indeed.parse_mosaic_result(r))
        self.assertEqual(j["apply_url"], "https://in.indeed.com/viewjob?jk=abc123")
        self.assertEqual((j["exp_min"], j["exp_max"], j["posted_days_ago"]), (3, OPEN_ENDED, 5))
        self.assertTrue(j["easy_apply"])
        self.assertIn("₹10,00,000", j["salary"])
        j2 = indeed.parse_mosaic_result(dict(r, indeedApplyEnabled=False))
        self.assertFalse(j2["easy_apply"])
        self.assertEqual(indeed.build_search_url(["ML Engineer"], "India"),
                         "https://in.indeed.com/jobs?q=ML+Engineer")

    def test_hirist(self):
        from tools.platforms import hirist
        item = {
            "id": 98765,
            "title": "Backend Python Developer",
            "companyName": "Acme Tech",
            "locations": ["Bengaluru"],
            "minSalary": 20,
            "maxSalary": 35,
            "minExp": 3,
            "maxExp": 6,
            "skills": ["Python", "FastAPI", "PostgreSQL"],
            "slug": "backend-python-developer-98765",
            "postedDate": "2 days ago",
        }
        j = normalize_job(hirist.parse_feed_item(item))
        self.assertEqual(j["platform"], "hirist")
        self.assertEqual(j["title"], "Backend Python Developer")
        self.assertEqual(j["company"], "Acme Tech")
        self.assertEqual((j["exp_min"], j["exp_max"]), (3, 6))
        self.assertIn("20–35 LPA", j["salary"])
        self.assertEqual(hirist.build_search_url(["Python"], "Bengaluru"),
                         "https://www.hirist.tech/search?query=Python&loc=Bengaluru")


class TestRegistry(unittest.TestCase):
    def test_registry(self):
        self.assertEqual(SUPPORTED_PLATFORMS, ["naukri", "instahyre", "hirist"])
        for p in SUPPORTED_PLATFORMS:
            cls = get_adapter_class(p)
            self.assertEqual(cls.name, p)
            self.assertTrue(cls.login_url.startswith("https://"))
        for p in PLANNED_PLATFORMS:
            with self.assertRaises(KeyError):
                get_adapter_class(p)

    def test_unknown_platform_fails_soft(self):
        from tools.search import search_jobs
        self.assertEqual(asyncio.run(search_jobs(["ML"], "India", 4, ["linkedin"])), [])

    def test_failing_adapter_fails_soft(self):
        from tools import search as s
        from tools.platforms import register

        register("boom", "tests.test_core:BoomAdapter")
        try:
            self.assertEqual(asyncio.run(s.search_jobs(["ML"], "India", 4, ["boom"])), [])
        finally:
            SUPPORTED_PLATFORMS.remove("boom")


from tools.platforms.base import PlatformAdapter  # noqa: E402


class BoomAdapter(PlatformAdapter):
    name = "boom"
    login_url = "https://example.com"

    async def is_logged_in(self, page):
        return False

    async def search(self, *a, **k):
        raise RuntimeError("site changed")

    async def apply(self, *a, **k):
        raise RuntimeError("nope")


class TestTracker(unittest.TestCase):
    def setUp(self):
        p = tracker.db_path()
        if p.exists():
            p.unlink()

    def test_record_and_summary(self):
        a = job(apply_url="https://www.naukri.com/job-a?src=x", title="A", company="CA")
        b = job(platform="indeed", apply_url="https://in.indeed.com/viewjob?jk=b", title="B", company="CB")
        c = job(platform="instahyre", apply_url="https://www.instahyre.com/job-c/", title="C", company="CC")
        tracker.record(a, "applied")
        tracker.record(b, "failed", "Unknown required field")
        tracker.record(c, "dry_run")
        self.assertTrue(tracker.has_applied("https://www.naukri.com/job-a"))
        self.assertFalse(tracker.has_applied(b["apply_url"]))
        # applied is never downgraded
        tracker.record(a, "failed", "later error")
        self.assertTrue(tracker.has_applied(a["apply_url"]))
        # failed can be upgraded
        tracker.record(b, "applied")
        self.assertTrue(tracker.has_applied(b["apply_url"]))
        # "already applied" skip counts as applied
        d = job(apply_url="https://www.naukri.com/job-d")
        tracker.record(d, "skipped", "already applied (detected on site)")
        self.assertTrue(tracker.has_applied(d["apply_url"]))

        s = tracker.get_application_summary(days=7)
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["by_status"], {"applied": 2, "dry_run": 1, "skipped": 1})
        self.assertEqual(s["by_platform"]["naukri"]["applied"][0]["job_title"], "A")
        self.assertEqual(s["by_platform"]["instahyre"]["dry_run"][0]["company"], "CC")
        with self.assertRaises(ValueError):
            tracker.record(a, "bogus")

    def test_days_window(self):
        tracker.record(job(apply_url="https://x/1"), "applied")
        import sqlite3
        conn = sqlite3.connect(str(tracker.db_path()))
        conn.execute("UPDATE applications SET applied_at = '2020-01-01T00:00:00+00:00'")
        conn.commit()
        conn.close()
        self.assertEqual(tracker.get_application_summary(days=7)["total"], 0)
        self.assertEqual(tracker.get_application_summary(days=100000)["total"], 1)


class TestBulkApplyNoBrowser(unittest.TestCase):
    """bulk_apply paths that need no browser: tracker skip + non-easy-apply skip."""

    def setUp(self):
        p = tracker.db_path()
        if p.exists():
            p.unlink()

    def test_skips(self):
        from tools.apply import bulk_apply
        done = job(apply_url="https://www.naukri.com/done")
        tracker.record(done, "applied")
        ext = job(apply_url="https://www.hirist.tech/j/ext.html", platform="hirist", easy_apply=False)
        res = asyncio.run(bulk_apply([done, ext], max_applications=5, dry_run=True))
        self.assertEqual(res["summary"]["already_applied"], 1)
        self.assertEqual(res["summary"]["skipped"], 1)
        self.assertEqual(res["summary"]["attempted"], 0)
        self.assertEqual(res["applied"], [])
        self.assertIn("summary", res)
        self.assertIn("failed", res)


if __name__ == "__main__":
    unittest.main(verbosity=2)
