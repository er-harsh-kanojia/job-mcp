"""Stopping a bulk-apply run promptly, and finding running tasks again."""

import asyncio
import threading
import time
import unittest

from tools import apply as apply_mod


class RunJobTest(unittest.TestCase):
    def test_stop_cuts_a_long_job_short(self):
        cancel = threading.Event()

        async def slow_job():
            await asyncio.sleep(60)  # e.g. waiting for a chatbot answer
            return {"status": "applied"}

        async def main():
            asyncio.get_running_loop().call_later(0.3, cancel.set)
            t = time.monotonic()
            with self.assertRaises(apply_mod.JobStopped):
                await apply_mod._run_job(slow_job(), cancel)
            return time.monotonic() - t

        self.assertLess(asyncio.run(main()), 3)

    def test_finished_job_returns_its_result(self):
        async def quick():
            return {"status": "applied"}
        self.assertEqual(asyncio.run(apply_mod._run_job(quick(), threading.Event())), {"status": "applied"})


class TaskListTest(unittest.TestCase):
    def test_list_and_meta(self):
        from fastapi.testclient import TestClient

        from api.app import create_app
        from api.tasks import manager

        with TestClient(create_app()) as client:
            async def body(task):
                task.emit("progress", {"done": 1, "total": 3})
                await asyncio.sleep(30)

            async def start():
                t = manager.start("apply", body)
                t.meta = {"dry_run": True, "requested": 3}
                await asyncio.sleep(0.05)
                return t.id

            tid = client.portal.call(start)
            running = client.get("/api/tasks?kind=apply&status=running").json()["tasks"]
            mine = [t for t in running if t["id"] == tid]
            self.assertEqual(len(mine), 1)
            self.assertEqual(mine[0]["meta"], {"dry_run": True, "requested": 3})
            self.assertEqual(mine[0]["progress"], {"done": 1, "total": 3})
            self.assertEqual(client.get("/api/tasks?kind=analyse&status=running").json()["tasks"], [])
            client.post(f"/api/tasks/{tid}/cancel")


if __name__ == "__main__":
    unittest.main()
