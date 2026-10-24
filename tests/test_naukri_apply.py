import unittest

from tools.autofill import answer_question
from tools.platforms.naukri import CLOSING_RE, SUCCESS_RE, _option_index, save_apply_outcome

SAVE_URL = ("https://www.naukri.com/myapply/saveApply?strJobsarr=[091026024533]&applytype=single"
            "&resId=281660172&ApplyMode=1&id=292721222&src=h&multiApplyResp=%7B%22091026024533%22%3A200%7D"
            "&jobTitle=AI%2FML%20Engineer%20GenAI%20%26%20LLM")


class SaveApplyOutcomeTest(unittest.TestCase):
    def test_accepted(self):
        self.assertEqual(save_apply_outcome(SAVE_URL), (True, "091026024533:200"))

    def test_rejected(self):
        url = SAVE_URL.replace("%3A200", "%3A409")
        ok, codes = save_apply_outcome(url)
        self.assertFalse(ok)
        self.assertIn("409", codes)

    def test_save_page_without_codes_counts_as_saved(self):
        self.assertEqual(save_apply_outcome("https://www.naukri.com/myapply/saveApply?x=1"),
                         (True, "no response codes"))

    def test_other_pages(self):
        self.assertIsNone(save_apply_outcome("https://www.naukri.com/job-listings-ml-engineer-123"))
        self.assertIsNone(save_apply_outcome(""))

    def test_chatbot_sign_off_is_not_a_question(self):
        self.assertTrue(CLOSING_RE.search("Thank you for your responses."))
        self.assertTrue(CLOSING_RE.search("Thanks for your time!"))
        self.assertIsNone(CLOSING_RE.search("How many years of experience do you have in MCP?"))
        self.assertIsNone(CLOSING_RE.search("Thank you. How many years of experience do you have in Python?"))

    def test_option_index_tolerates_spacing_and_blank_labels(self):
        self.assertEqual(_option_index(["Yes ", "No"], "yes"), 0)
        self.assertIsNone(_option_index(["", ""], "Yes"))  # used to crash with "'Yes' is not in list"
        self.assertIsNone(_option_index(["Immediately"], None))

    def test_applied_to_banner(self):
        self.assertTrue(SUCCESS_RE.search('Applied to "AI/ML Engineer GenAI & LLM"'))
        self.assertIsNone(SUCCESS_RE.search("Roles you might be interested in"))


class ChatbotAnswerTest(unittest.TestCase):
    PROFILE = {"autofill": {"experience": {"python": "4", "rag": "3"}, "previous_employers": ["Kite Labs"]}}

    def ask(self, q):
        return answer_question(q, self.PROFILE, kind="radio", options=["Yes", "No"])

    def test_employer_question(self):
        self.assertEqual(self.ask("Have you worked as a full-time employee with InfoEdge?"), "No")
        self.assertEqual(self.ask("Have you worked as a full-time employee with Kite Labs?"), "Yes")

    def test_built_or_deployed_uses_skills(self):
        self.assertEqual(self.ask("Have you built RAG pipelines in production?"), "Yes")
        # skills the profile doesn't list stay unanswered rather than guessed
        self.assertIsNone(self.ask("Have you built and deployed AI/ML solutions using REST APIs and Docker?"))


if __name__ == "__main__":
    unittest.main()
