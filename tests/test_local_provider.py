"""Local (OpenAI-compatible Chat Completions) provider, with a fake client."""

import asyncio
import json
import os
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from pydantic import BaseModel

from tools.ai.providers import base
from tools.ai.providers.local_provider import LocalProvider


class Out(BaseModel):
    verdict: str
    score: int


class FakeChat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        if kw.get("stream"):
            async def gen():
                for piece in ("Tell me ", "about LoRA."):
                    yield NS(choices=[NS(delta=NS(content=piece))])
            return gen()
        content, finish = self.replies.pop(0)
        return NS(model=kw["model"], choices=[NS(finish_reason=finish, message=NS(content=content))])


def provider_with(chat: FakeChat, model: str = "openai/gpt-oss-20b") -> LocalProvider:
    p = LocalProvider()
    p.set_client_factory(lambda: NS(chat=NS(completions=chat)))
    p._models = lambda: [model]  # pretend the server lists this model
    return p


def run(coro):
    return asyncio.run(coro)


class LocalProviderTest(unittest.TestCase):
    def test_structured_json_with_schema_and_reasoning_effort(self):
        chat = FakeChat([('```json\n{"verdict": "good", "score": 7}\n```', "stop")])
        p = provider_with(chat)
        out, used = run(p.structured(Out, system="sys", messages=[{"role": "user", "content": "hi"}], max_tokens=50000))
        self.assertEqual(out.model_dump(), {"verdict": "good", "score": 7})
        self.assertEqual(used, "openai/gpt-oss-20b")
        call = chat.calls[0]
        self.assertEqual(call["response_format"]["type"], "json_schema")
        self.assertEqual(call["response_format"]["json_schema"]["name"], "Out")
        self.assertEqual(call["reasoning_effort"], "low")
        self.assertEqual(call["max_tokens"], 16000)  # capped for local context sizes
        self.assertEqual(call["messages"][0], {"role": "system", "content": "sys"})

    def test_cut_off_answer_is_retried(self):
        chat = FakeChat([('{"verdict": "go', "length"), ('{"verdict": "ok", "score": 3}', "stop")])
        out, _ = run(provider_with(chat).structured(Out, system="s", messages=[{"role": "user", "content": "x"}]))
        self.assertEqual(out.score, 3)
        self.assertEqual(len(chat.calls), 2)

    def test_qwen3_gets_no_think_and_no_reasoning_param(self):
        chat = FakeChat([('{"verdict": "ok", "score": 1}', "stop")])
        run(provider_with(chat, model="qwen/qwen3-8b").structured(Out, system="s", messages=[{"role": "user", "content": "x"}]))
        call = chat.calls[0]
        self.assertTrue(call["messages"][0]["content"].endswith("/no_think"))
        self.assertNotIn("reasoning_effort", call)

    def test_streaming(self):
        chat = FakeChat([])

        async def collect():
            return "".join([d async for d in provider_with(chat).stream_text(system="s", messages=[{"role": "user", "content": "q"}])])
        self.assertEqual(run(collect()), "Tell me about LoRA.")
        self.assertTrue(chat.calls[0]["stream"])

    def test_not_configured_when_no_server_answers(self):
        with mock.patch.dict(os.environ, {"JOB_MCP_LOCAL_BASE_URL": "http://127.0.0.1:9/v1"}):
            p = LocalProvider()
            self.assertFalse(p.is_configured())
            self.assertEqual(p.model(), "local-model")
            err = p.not_configured()
            self.assertIsInstance(err, base.AIError)
            self.assertEqual(err.code, "ai_not_configured")
            self.assertIn("127.0.0.1:9", err.message)
            self.assertEqual(p.info()["base_url"], "http://127.0.0.1:9/v1")

    def test_listed_in_settings(self):
        from tools.ai import providers
        self.assertIn("local", providers.PROVIDERS)
        ids = [p["id"] for p in providers.settings()["providers"]]
        self.assertEqual(ids[-1], "local")


if __name__ == "__main__":
    unittest.main()
