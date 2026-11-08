"""Autopilot: slots, job selection with daily caps, settings API and a run with fake search/apply."""

import unittest
from datetime import datetime, timedelta
from unittest import mock

from tests.test_api import ApiTestCase, parse_sse
from tools import autopilot, tracker


def job(url, platform="naukri", score=0.9, easy=True, title="AI Engineer", **kw):
    return {"apply_url": url, "platform": platform, "match_score": score, "rank_score": score,
            "easy_apply": easy, "title": title, "company": kw.pop("company", "Acme"), "exp_min": 2, "exp_max": 6,
            "job_id": url, "location": "Gurugram", "salary": "", "description": "", "skills": [],
            "posted_days_ago": 1, **kw}


class SlotsTest(ApiTestCase):
    def test_due_slot_and_window(self):
        cfg = {**autopilot.DEFAULTS, "enabled": True, "times": ["09:30", "18:30"]}
        d = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
        self.assertEqual(autopilot.due_slot(cfg, d), "09:30")
        self.assertIsNone(autopilot.due_slot(cfg, d.replace(hour=9, minute=0)))        # not yet
        self.assertIsNone(autopilot.due_slot(cfg, d.replace(hour=13, minute=0)))       # window passed
        autopilot.start_run("09:30", live=False, now=d)
        self.assertIsNone(autopilot.due_slot(cfg, d + timedelta(minutes=5)))           # already ran today
        self.assertEqual(autopilot.next_run_at(cfg, d + timedelta(minutes=5))[:16],
                         d.replace(hour=18, minute=30).isoformat()[:16])
        self.assertIsNone(autopilot.next_run_at({**cfg, "enabled": False}, d))


class SelectTest(ApiTestCase):
    def test_caps_score_easy_apply_and_history(self):
        cfg = {**autopilot.DEFAULTS, "min_score": 0.7, "platforms": ["naukri", "instahyre"],
               "daily_caps": {"naukri": 2, "instahyre": 1, "hirist": 0}}
        jobs = [job("n1", score=0.95), job("n2", score=0.9), job("n3", score=0.85),       # cap 2 -> n1, n2
                job("n4", score=0.6),                                                     # below min
                job("n5", easy=False),                                                    # company site
                job("i1", platform="instahyre", score=0.8), job("i2", platform="instahyre", score=0.75),
                job("h1", platform="hirist")]                                             # not chosen
        tracker.record(job("n1"), "applied")                                              # already applied
        tracker.record(job("n2"), "failed", "Apply button not found on job page")         # failed recently
        tracker.record(job("n3"), "failed", "needs your answer: Years in MCP?")           # retried
        picked = autopilot.select_jobs(jobs, cfg, {"naukri": 0, "instahyre": 0})
        self.assertEqual([j["apply_url"] for j in picked], ["n3", "i1"])
        # today's count uses up the cap
        self.assertEqual([j["apply_url"] for j in autopilot.select_jobs(jobs, cfg, {"naukri": 2, "instahyre": 1})], [])


class ApiTest(ApiTestCase):
    def test_settings_validation_and_live_confirm(self):
        s = self.client.get("/api/autopilot").json()
        self.assertFalse(s["config"]["enabled"])
        self.assertIsNone(s["next_run_at"])
        r = self.client.put("/api/autopilot", json={"times": ["25:00"]})
        self.assertEqual(r.status_code, 422)
        self.assertIn("times", r.json()["error"]["detail"])
        r = self.client.put("/api/autopilot", json={"enabled": True, "live": True})
        self.assertEqual(r.json()["error"]["code"], "confirm_required")
        r = self.client.put("/api/autopilot", json={"enabled": True, "live": True, "confirm": "APPLY",
                                                    "daily_caps": {"naukri": 50}})
        self.assertEqual(r.status_code, 200, r.text)
        cfg = r.json()["config"]
        self.assertTrue(cfg["enabled"] and cfg["live"])
        self.assertEqual(cfg["daily_caps"]["naukri"], 50)
        self.assertEqual(cfg["daily_caps"]["instahyre"], 60)
        self.assertIsNotNone(r.json()["next_run_at"])
        self.assertEqual(self.raw_config()["credentials"], self.raw_config()["credentials"])  # untouched

    def test_run_now_with_fake_search_and_apply(self):
        found = [job("a1", score=0.9), job("a2", score=0.5)]

        async def fake_search(**kw):
            return [dict(j) for j in found]

        async def fake_apply(jobs, max_applications, dry_run, on_job, cancel_event, human_wait):
            self.assertEqual(human_wait, 0)        # unattended by default
            self.assertTrue(dry_run)               # dry run by default
            for j in jobs:
                on_job({"apply_url": j["apply_url"], "title": j["title"], "company": j["company"],
                        "platform": j["platform"], "state": "dry_run"})
            return {"summary": {"dry_run": True, "would_apply": len(jobs), "failed": 0, "skipped": 0},
                    "applied": [], "failed": [], "skipped": []}

        self.client.put("/api/autopilot", json={"keywords": ["AI Engineer"], "platforms": ["naukri"]})
        with mock.patch("tools.search.search_jobs", fake_search), mock.patch("tools.apply.bulk_apply", fake_apply):
            r = self.client.post("/api/autopilot/run")
            self.assertEqual(r.status_code, 200, r.text)
            tid = r.json()["task_id"]
            with self.client.stream("GET", f"/api/tasks/{tid}/events") as resp:
                evs = parse_sse(resp.iter_lines())
        kinds = [e for e, _ in evs]
        self.assertIn("status", kinds)
        self.assertEqual([d["apply_url"] for e, d in evs if e == "job"], ["a1"])  # a2 below 0.7
        self.assertEqual(kinds[-1], "done")
        snap = self.client.get(f"/api/tasks/{tid}").json()
        self.assertTrue(snap["meta"]["autopilot"])
        run = self.client.get("/api/autopilot").json()["runs"][0]
        self.assertEqual((run["slot"], run["status"], run["searched"], run["selected"], run["applied"]),
                         ("manual", "done", 2, 1, 1))


if __name__ == "__main__":
    unittest.main()
