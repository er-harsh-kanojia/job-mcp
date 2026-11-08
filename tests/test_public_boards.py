"""Himalayas and YC job board adapters (offline: HTTP is faked), and how the API treats public boards."""

import asyncio
import html
import json
import time
import unittest
from contextlib import asynccontextmanager
from unittest import mock

import httpx

from tests.test_api import ApiTestCase
from tools.platforms import himalayas, ycombinator
from tools.platforms.public import PublicBoardAdapter, wanted_country

NOW = 1_800_000_000.0


def him_item(title="AI/ML Engineer", slug="ai-ml-engineer", restrictions=("India",), seniority=("Mid-level",), **kw):
    return {"title": title, "companyName": kw.get("company", "Acme AI"), "locationRestrictions": list(restrictions),
            "seniority": list(seniority), "minSalary": kw.get("min"), "maxSalary": kw.get("max"),
            "currency": "USD", "salaryPeriod": "annual", "description": "<p>Build LLM and RAG systems in Python</p>",
            "pubDate": int(NOW - 3 * 86400), "guid": f"https://himalayas.app/companies/acme/jobs/{slug}",
            "applicationLink": f"https://himalayas.app/companies/acme/jobs/{slug}?utm_source=api",
            "categories": ["Machine-Learning-Engineer"]}


def yc_posting(pid, title, location="Bengaluru, KA, IN", visa="US citizenship/visa not required", **kw):
    return {"id": pid, "title": title, "url": f"/companies/acme/jobs/{pid}-x", "location": location, "visa": visa,
            "type": "Full-time", "prettyRole": "Engineering", "roleSpecificType": kw.get("specific", "Backend"),
            "salaryRange": kw.get("salary", "₹2M - ₹3.5M INR"), "equityRange": "", "minExperience": kw.get("exp", "3+ years"),
            "skills": kw.get("skills", []), "companyName": kw.get("company", "Acme"), "companyOneLiner": "AI for X",
            "companyBatchName": "W24", "createdAt": kw.get("created", "3 days")}


def yc_page(postings):
    data = json.dumps({"component": "WaasJobListingsPage", "props": {"jobPostings": postings}})
    return f'<div id="app" data-page="{html.escape(data, quote=True)}"></div>'


def fake_http(handler):
    """Patch PublicBoardAdapter.http to serve responses from ``handler(request)``."""

    @asynccontextmanager
    async def http(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            yield client

    return mock.patch.object(PublicBoardAdapter, "http", http)


class LocationTest(unittest.TestCase):
    def test_wanted_country(self):
        self.assertEqual(wanted_country("Gurugram"), "India")
        self.assertEqual(wanted_country("Bangalore, Karnataka"), "India")
        self.assertIsNone(wanted_country("Remote"))
        self.assertIsNone(wanted_country(""))
        self.assertEqual(wanted_country("Berlin, Germany"), "Germany")


class HimalayasTest(unittest.TestCase):
    def test_parse_job(self):
        j = himalayas.parse_job(him_item(min=60000, max=90000), now=NOW)
        self.assertEqual(j["apply_url"], "https://himalayas.app/companies/acme/jobs/ai-ml-engineer")
        self.assertEqual((j["location"], j["salary"]), ("Remote · India", "USD 60k–90k / yr"))
        self.assertEqual((j["exp_min"], j["exp_max"], j["posted_days_ago"]), (2, 5, 3))
        self.assertFalse(j["easy_apply"])
        self.assertEqual(himalayas.parse_job(him_item(restrictions=()), now=NOW)["location"], "Remote (worldwide)")
        self.assertEqual(himalayas.experience_from_seniority(["Entry-level", "Senior"]), (0, 99))
        self.assertEqual(himalayas.experience_from_seniority([]), (-1, -1))

    def test_search_uses_country_and_pages(self):
        calls = []

        def handler(req):
            calls.append(dict(req.url.params))
            page = int(req.url.params["page"])
            items = [him_item(slug=f"job-{page}-{i}") for i in range(20 if page == 1 else 5)]
            return httpx.Response(200, json={"jobs": items})

        with fake_http(handler):
            jobs = asyncio.run(himalayas.HimalayasAdapter().search(["ML Engineer"], "Noida", 3, limit=40))
        self.assertEqual(len(jobs), 25)
        self.assertEqual([c["page"] for c in calls], ["1", "2"])           # stops on a short page
        self.assertEqual(calls[0]["country"], "India")
        self.assertEqual(calls[0]["q"], "ML Engineer")

    def test_unknown_country_falls_back_to_worldwide(self):
        calls = []

        def handler(req):
            calls.append(dict(req.url.params))
            items = [] if "country" in req.url.params else [him_item(restrictions=())]
            return httpx.Response(200, json={"jobs": items})

        with fake_http(handler):
            jobs = asyncio.run(himalayas.HimalayasAdapter().search(["ML"], "Atlantis", 3, limit=20))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(calls[-1].get("worldwide"), "true")


class YCombinatorTest(unittest.TestCase):
    def test_keyword_terms_and_matching(self):
        terms = ycombinator.keyword_terms(["AI/ML Engineer"])
        self.assertIn("machine learning", terms)
        self.assertTrue(ycombinator.matches_terms("Senior AI Engineer Backend", terms))
        self.assertFalse(ycombinator.matches_terms("Account Executive Sales", terms))
        self.assertTrue(ycombinator.matches_terms("anything", ycombinator.keyword_terms(["Software Engineer"])))

    def test_parse_posting(self):
        j = ycombinator.parse_posting(yc_posting(7, "ML Engineer", visa="Will sponsor", exp="Any (new grads ok)"))
        self.assertEqual(j["apply_url"], "https://www.ycombinator.com/companies/acme/jobs/7-x")
        self.assertTrue(j["visa_sponsored"])
        self.assertEqual((j["exp_min"], j["exp_max"], j["posted_days_ago"]), (0, 99, 3))
        self.assertIn("YC W24", j["description"])

    def test_search_filters_role_location_and_visa(self):
        pages = {
            "/jobs/role/software-engineer/india": [yc_posting(1, "Senior AI Engineer"),
                                                   yc_posting(2, "Sales Lead", specific="Sales")],
            "/jobs/role/software-engineer": [yc_posting(1, "Senior AI Engineer"),                     # duplicate
                                             yc_posting(3, "ML Engineer", location="San Francisco, CA, US",
                                                        visa="US citizen/visa only"),                  # US-only
                                             yc_posting(4, "LLM Engineer", location="San Francisco, CA, US",
                                                        visa="Will sponsor")],
            "/jobs/role/software-engineer/remote": [yc_posting(5, "Machine Learning Engineer", location="Remote (US)",
                                                               visa="US citizen/visa only")],               # US-only
            "/jobs/role/science": [],
        }
        seen = []

        def handler(req):
            seen.append(req.url.path)
            return httpx.Response(200, text=yc_page(pages.get(req.url.path, [])))

        with fake_http(handler):
            jobs = asyncio.run(ycombinator.YCombinatorAdapter().search(["AI/ML Engineer"], "Gurugram", 3, limit=40))
        self.assertEqual(seen[0], "/jobs/role/software-engineer/india")
        self.assertEqual(sorted(j["job_id"] for j in jobs), ["1", "4"])
        self.assertTrue(next(j for j in jobs if j["job_id"] == "4")["visa_sponsored"])
        self.assertTrue(all(not k.startswith("_") for j in jobs for k in j))


class ApiTest(ApiTestCase):
    def test_public_boards_need_no_login(self):
        plats = {p["id"]: p for p in self.client.get("/api/platforms").json()["platforms"]}
        for pid in ("himalayas", "ycombinator"):
            self.assertTrue(plats[pid]["live"])
            self.assertEqual(plats[pid]["session"], "logged_in")
            self.assertFalse(plats[pid]["login_required"])
        self.assertTrue(plats["naukri"]["login_required"])
        for pid in ("welcometothejungle", "hiringcafe"):
            self.assertFalse(plats[pid]["live"])
        r = self.client.post("/api/platforms/himalayas/login", json={})
        self.assertEqual(r.json()["error"]["code"], "no_login_needed")
        self.assertEqual(self.client.post("/api/platforms/ycombinator/check").json()["session"], "logged_in")

    def test_autopilot_only_offers_apply_platforms(self):
        r = self.client.put("/api/autopilot", json={"platforms": ["naukri", "himalayas"]})
        self.assertEqual(r.status_code, 422)
        self.assertIn("platforms", r.json()["error"]["detail"])


if __name__ == "__main__":
    unittest.main()
