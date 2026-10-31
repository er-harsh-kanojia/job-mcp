import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from tools.normalize import detect_visa_sponsorship, normalize_job
from tools.search import filter_jobs, score_jobs
from tools import tracker
from api.routes_jobs import record_external_apply, ExternalApplyBody
from api.util import public_job


class TestVisaSponsorship(unittest.TestCase):
    def test_positive_visa_signals(self):
        # Explicit visa sponsorship phrases
        self.assertTrue(detect_visa_sponsorship(description="Full work visa sponsorship and relocation support provided."))
        self.assertTrue(detect_visa_sponsorship(title="Senior ML Engineer (Relocation / Visa Support)"))
        self.assertTrue(detect_visa_sponsorship(description="EU Blue Card sponsorship available for qualified candidates."))
        self.assertTrue(detect_visa_sponsorship(description="We offer H1B sponsorship and H1B transfer."))
        self.assertTrue(detect_visa_sponsorship(description="Tier 2 / Skilled Worker Visa provided with relocation allowance."))
        self.assertTrue(detect_visa_sponsorship(description="Work permit sponsorship available."))

    def test_visa_sponsoring_companies(self):
        # Well-known global companies known for visa sponsorship & relocation
        self.assertTrue(detect_visa_sponsorship(company="Booking.com"))
        self.assertTrue(detect_visa_sponsorship(company="Amazon Web Services"))
        self.assertTrue(detect_visa_sponsorship(company="Spotify"))
        self.assertTrue(detect_visa_sponsorship(company="Adyen"))
        self.assertTrue(detect_visa_sponsorship(company="Revolut"))
        self.assertTrue(detect_visa_sponsorship(company="Palantir"))

    def test_negative_visa_signals(self):
        # Jobs stating they do NOT sponsor
        self.assertFalse(detect_visa_sponsorship(description="We cannot sponsor work visas at this time."))
        self.assertFalse(detect_visa_sponsorship(description="Must be legally authorized to work without visa sponsorship."))
        self.assertFalse(detect_visa_sponsorship(description="No visa sponsorship is available for this role."))
        self.assertFalse(detect_visa_sponsorship(description="Applicant must be authorized to work without sponsorship."))
        # Regular job without visa mentions
        self.assertFalse(detect_visa_sponsorship(title="Java Developer", description="Spring boot in Gurgaon", company="Random Co"))

    def test_normalize_job_sets_visa_sponsored(self):
        j1 = normalize_job({
            "title": "Staff AI Engineer",
            "company": "Booking.com",
            "apply_url": "https://careers.booking.com/job/1",
            "description": "Full visa sponsorship to Amsterdam.",
        })
        self.assertTrue(j1["visa_sponsored"])
        pub = public_job(j1)
        self.assertIn("visa_sponsored", pub)
        self.assertTrue(pub["visa_sponsored"])

        j2 = normalize_job({
            "title": "Software Engineer",
            "company": "Local Agency",
            "apply_url": "https://naukri.com/job/2",
            "description": "General web developer.",
        })
        self.assertFalse(j2["visa_sponsored"])
        self.assertFalse(public_job(j2)["visa_sponsored"])

    def test_filter_jobs_visa_sponsored_only(self):
        j_visa = normalize_job({
            "apply_url": "https://example.com/visa",
            "title": "ML Engineer",
            "company": "Booking.com",
            "visa_sponsored": True,
        })
        j_normal = normalize_job({
            "apply_url": "https://example.com/normal",
            "title": "ML Engineer",
            "company": "Local Co",
            "visa_sponsored": False,
        })
        score_jobs([j_visa, j_normal], ["ML Engineer"], 4, ["Python"], ["Remote"])
        
        # When visa_sponsored_only is True, only visa job is kept
        only_visa = filter_jobs([j_visa, j_normal], min_match_score=0.1, experience_years=4, visa_sponsored_only=True)
        self.assertEqual(len(only_visa), 1)
        self.assertEqual(only_visa[0]["apply_url"], "https://example.com/visa")

        # When visa_sponsored_only is False, all matching jobs are kept
        all_jobs = filter_jobs([j_visa, j_normal], min_match_score=0.1, experience_years=4, visa_sponsored_only=False)
        self.assertEqual(len(all_jobs), 2)


class TestExternalApply(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jobmcp_test_ext_"))
        self.orig_db = os.environ.get("JOB_MCP_DB")
        os.environ["JOB_MCP_DB"] = str(self.tmp / "test_applications.db")

    def tearDown(self):
        if self.orig_db:
            os.environ["JOB_MCP_DB"] = self.orig_db
        else:
            os.environ.pop("JOB_MCP_DB", None)

    def test_record_external_apply(self):
        url = "https://external.employer.com/apply/job-999"
        res = record_external_apply(ExternalApplyBody(
            apply_url=url,
            title="Senior GenAI Engineer",
            company="Booking.com",
            platform="naukri",
            location="Amsterdam",
        ))
        self.assertEqual(res, {"ok": True, "apply_url": url, "status": "applied"})

        # Tracker must now report has_applied as True
        self.assertTrue(tracker.has_applied(url))

        # Check recorded row in tracker applications
        apps = tracker.list_applications()
        self.assertTrue(any(a["apply_url"] == url and a["status"] == "applied" for a in apps))
        found = next(a for a in apps if a["apply_url"] == url)
        self.assertEqual(found["title"], "Senior GenAI Engineer")
        self.assertEqual(found["company"], "Booking.com")
        self.assertEqual(found["error"], "Applied externally on employer site")


if __name__ == "__main__":
    unittest.main()
