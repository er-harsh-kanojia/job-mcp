"""Report history, comparison with a previous report, and report downloads."""

import unittest

from tests.test_api import COMPARE_JSON, RESUME_LINES, ApiTestCase, make_docx


class ReportsTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.use("anthropic")
        self.client.put("/api/settings/ai", json={"provider": "anthropic"})
        self.assertEqual(self.upload_resume().status_code, 200)

    def ai_calls(self) -> int:
        return len(self.script.calls)

    def test_first_report_has_no_comparison(self):
        review, _ = self.analyse()
        self.assertNotIn("comparison", review)

    def test_same_resume_compares_without_an_ai_call(self):
        first, _ = self.analyse()
        before = self.ai_calls()
        second, evs = self.analyse()
        self.assertEqual(self.ai_calls() - before, 2)  # review + prep only
        c = second["comparison"]
        self.assertTrue(c["identical_resume"])
        self.assertEqual(c["previous_review_id"], first["id"])
        self.assertTrue(all(p["outcome"] == "still_open" for p in c["previous"]))
        label = [d for e, d in evs if e == "step" and d["index"] == 1][0]["label"]
        self.assertIn("and your report from", label)

    def test_changed_resume_is_compared_with_the_previous_report(self):
        first, _ = self.analyse()
        self.client.patch(f"/api/resume/issues/{first['issues'][0]['id']}", json={"status": "fixed"})
        self.upload_resume(make_docx(RESUME_LINES + ["Led a team of 3 engineers."]))
        before = self.ai_calls()
        second, _ = self.analyse()
        self.assertEqual(self.ai_calls() - before, 3)  # review + compare + prep
        c = second["comparison"]
        self.assertFalse(c["identical_resume"])
        self.assertEqual(c["summary"], COMPARE_JSON["summary"])
        self.assertEqual(c["changes"], COMPARE_JSON["changes"])
        self.assertEqual([p["outcome"] for p in c["previous"]], ["resolved", "partly", "still_open"])
        self.assertEqual(c["previous"][0]["previous_status"], "fixed")
        self.assertEqual(c["new_issue_ids"], [second["issues"][2]["id"]])  # 99 is out of range
        self.assertEqual(c["overall_before"], c["overall_after"])  # same fake scores
        # history lists both, newest first, with the link between them
        hist = self.client.get("/api/resume/reviews?all=true").json()["reviews"]
        self.assertEqual([h["review_id"] for h in hist], [second["id"], first["id"]])
        self.assertEqual(hist[0]["compared_to"], first["id"])
        self.assertEqual(self.client.get(f"/api/resume/reviews/{first['id']}").json()["id"], first["id"])

    def test_compare_to_zero_skips_the_comparison(self):
        self.analyse()
        r = self.client.post("/api/resume/analyse", json={"target_role": "GenAI Engineer", "compare_to": 0})
        review = self.events(r.json()["task_id"])[-1][1]["review"]
        self.assertNotIn("comparison", review)
        r = self.client.post("/api/resume/analyse", json={"target_role": "GenAI Engineer", "compare_to": 999})
        self.assertEqual(r.status_code, 404)

    def test_report_downloads(self):
        self.analyse()
        self.upload_resume(make_docx(RESUME_LINES + ["Led a team of 3 engineers."]))
        review, _ = self.analyse()
        base = f"/api/resume/reviews/{review['id']}/report"
        md = self.client.get(base + "?format=md")
        self.assertEqual(md.status_code, 200)
        self.assertIn("attachment;", md.headers["content-disposition"])
        self.assertIn(".md", md.headers["content-disposition"])
        self.assertIn("# Resume report: GenAI Engineer", md.text)
        self.assertIn("Compared with your report from", md.text)
        self.assertIn(review["issues"][0]["title"], md.text)
        html = self.client.get(base + "?format=html")
        self.assertIn("<h1>Resume report: GenAI Engineer</h1>", html.text)
        pdf = self.client.get(base + "?format=pdf")
        if pdf.status_code == 500 and "pdf_failed" in pdf.text:
            self.skipTest("Chromium unavailable for PDF rendering")
        self.assertEqual(pdf.status_code, 200, pdf.text[:300])
        self.assertEqual(pdf.headers["content-type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertEqual(self.client.get("/api/resume/reviews/999/report?format=md").status_code, 404)
        self.assertEqual(self.client.get(base + "?format=docx").status_code, 422)


if __name__ == "__main__":
    unittest.main()
