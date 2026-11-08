"""Answer bank, pending questions, and last-working-day / joining answers."""

import unittest
from datetime import date

from tests.test_api import ApiTestCase
from tools import answers
from tools.autofill import answer_question, days_to_join, lwd_date


class AnswerBankTest(ApiTestCase):  # ApiTestCase gives each test its own temp DB
    def test_saved_answer_is_reused_with_options(self):
        answers.save("How many years of experience do you have in MCP?", "1", source="you")
        prof = {"autofill": {}}
        # same question, different case/punctuation
        self.assertEqual(answer_question("how many years of experience do you have in MCP", prof), "1")
        # maps onto the offered options
        self.assertEqual(answer_question("How many years of experience do you have in MCP?", prof,
                                         kind="radio", options=["0-1 years", "2-3 years"]), "0-1 years")
        # no fuzzy matching across different skills
        self.assertIsNone(answer_question("How many years of experience do you have in Kafka?", prof))

    def test_saved_answer_beats_rules(self):
        answers.save("What is your expected CTC?", "Negotiable")
        prof = {"autofill": {"expected_ctc": "25"}}
        self.assertEqual(answer_question("What is your expected CTC?", prof), "Negotiable")

    def test_pending_counts_repeats_and_resolves_into_bank(self):
        job = {"platform": "naukri", "title": "AI Engineer", "company": "Acme", "apply_url": "u1"}
        answers.add_pending("Current Organization Name", kind="text", job=job)
        answers.add_pending("current organization name?", kind="text", job=job)
        [p] = answers.list_pending()
        self.assertEqual(p["times_seen"], 2)
        self.assertEqual(p["company"], "Acme")
        saved = answers.resolve_pending(p["id"], "Acme Labs")
        self.assertEqual(saved["answer"], "Acme Labs")
        self.assertEqual(answers.list_pending(), [])
        self.assertEqual(answers.lookup("Current organization name"), "Acme Labs")
        # a question that's already answered isn't added again
        answers.add_pending("Current Organization Name", job=job)
        self.assertEqual(answers.list_pending(), [])

    def test_api(self):
        r = self.client.post("/api/answers", json={"question": "Years in FastAPI?", "answer": "5"})
        self.assertEqual(r.status_code, 200, r.text)
        aid = r.json()["id"]
        answers.add_pending("Which domain experience do you have?", kind="chips", options=["BFSI", "Healthcare"])
        got = self.client.get("/api/answers").json()
        self.assertEqual([a["question"] for a in got["answers"]], ["Years in FastAPI?"])
        self.assertEqual(got["pending"][0]["options"], ["BFSI", "Healthcare"])
        pid = got["pending"][0]["id"]
        self.assertEqual(self.client.put(f"/api/answers/{aid}", json={"answer": "3"}).json()["answer"], "3")
        self.assertEqual(self.client.post(f"/api/answers/pending/{pid}", json={"answer": "BFSI"}).status_code, 200)
        got = self.client.get("/api/answers").json()
        self.assertEqual(got["pending"], [])
        self.assertEqual(len(got["answers"]), 2)
        self.assertEqual(self.client.delete(f"/api/answers/{aid}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/answers/{aid}").status_code, 404)
        self.assertEqual(self.client.post("/api/answers/pending/999", json={"answer": "x"}).status_code, 404)


class JoiningAnswersTest(unittest.TestCase):
    T = date(2026, 11, 4)

    def test_lwd_parsing(self):
        for v in ("20 Febuary", "20 Feb 2027", "2027-02-20", "20/02/2027", "Feb 20", "20th February"):
            self.assertEqual(lwd_date(v, self.T), date(2027, 2, 20), v)
        self.assertIsNone(lwd_date("Currently Working", self.T))

    def test_days_to_join(self):
        self.assertEqual(days_to_join({"last_working_day": "20 Feb 2027"}, self.T), 109)
        self.assertEqual(days_to_join({"last_working_day": "20 Feb 2027", "can_join_within_days": 30}, self.T), 30)
        self.assertEqual(days_to_join({"notice_period": "1 month"}, self.T), 30)

    def test_notice_and_joining_questions(self):
        prof = {"autofill": {"notice_period": "30 days", "last_working_day": "20 Feb 2027",
                             "can_join_within_days": 30}}
        ask = lambda q, **kw: answer_question(q, prof, **kw)  # noqa: E731
        self.assertEqual(ask("What is your notice period?", kind="radio",
                             options=["Immediate", "1 Month", "Serving Notice Period"]), "Serving Notice Period")
        self.assertEqual(ask("Are you serving notice period?", kind="radio", options=["Yes", "No"]), "Yes")
        self.assertEqual(ask("Last working day", kind="date"), "2027-02-20")
        self.assertEqual(ask("Can you join within 30 days?", kind="radio", options=["Yes", "No"]), "Yes")
        self.assertEqual(ask("Can you join within 15 days?", kind="radio", options=["Yes", "No"]), "No")


if __name__ == "__main__":
    unittest.main()
