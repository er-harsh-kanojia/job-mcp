"""Local model provider: any OpenAI-compatible Chat Completions server.

Works with LM Studio (default, http://localhost:1234/v1), Ollama
(http://localhost:11434/v1), llama.cpp server, vLLM, or a hosted
OpenAI-compatible API such as OpenRouter.

* structured: ``chat.completions.create`` with ``response_format`` = JSON schema
  (validated again with pydantic by the caller)
* chat: streamed ``chat.completions`` deltas
* configuration (.env, all optional):
    JOB_MCP_LOCAL_BASE_URL  server URL, default http://localhost:1234/v1
    JOB_MCP_LOCAL_MODEL     model id; default: the first chat model the server lists
    JOB_MCP_LOCAL_API_KEY   only for hosted servers that need one
    JOB_MCP_LOCAL_EFFORT    reasoning effort for models that support it (gpt-oss), default "low"
    JOB_MCP_LOCAL_MAX_TOKENS  cap on output tokens per request, default 16000
* "configured" means the server answers; the check is cached for a few seconds.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from typing import Any, AsyncIterator

from pydantic import BaseModel

from .base import AIError, Provider, flatten
from .openai_provider import strict_schema

DEFAULT_BASE_URL = "http://localhost:1234/v1"
PROBE_TTL = 10.0
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


def _base_url() -> str:
    return (os.environ.get("JOB_MCP_LOCAL_BASE_URL", "").strip() or DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    return os.environ.get("JOB_MCP_LOCAL_API_KEY", "").strip() or "local"


class LocalProvider(Provider):
    id = "local"
    name = "Local model (LM Studio / Ollama)"
    short = "Local AI"
    env_key = "JOB_MCP_LOCAL_BASE_URL"
    model_env = "JOB_MCP_LOCAL_MODEL"
    chat_model_env = "JOB_MCP_LOCAL_CHAT_MODEL"
    default_model = ""
    default_effort = "low"
    default_chat_effort = "low"

    def __init__(self) -> None:
        super().__init__()
        self._probe: tuple[float, str, list[str]] = (0.0, "", [])

    # --------------------------------------------------------------- config
    def _models(self) -> list[str]:
        """Chat model ids the server lists ([] if it isn't reachable). Cached briefly."""
        at, url, models = self._probe
        base = _base_url()
        if url == base and time.monotonic() - at < PROBE_TTL:
            return models
        try:
            req = urllib.request.Request(base + "/models", headers={"Authorization": f"Bearer {_api_key()}"})
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = [m["id"] for m in data.get("data", []) if "embed" not in m.get("id", "").lower()]
        except Exception:
            models = []
        self._probe = (time.monotonic(), base, models)
        return models

    def is_configured(self) -> bool:
        return self._client_factory is not None or bool(self._models())

    def model(self) -> str:
        env = os.environ.get(self.model_env, "").strip()
        if env:
            return env
        models = self._models()
        return models[0] if models else "local-model"

    def info(self) -> dict:
        return {**super().info(), "base_url": _base_url()}

    def not_configured(self) -> AIError:
        return AIError("ai_not_configured",
                       f"No local model server is answering at {_base_url()}. Start the server in LM Studio "
                       "(Developer, Start server) with a model loaded, or set JOB_MCP_LOCAL_BASE_URL in .env.")

    def _make_client(self):
        import openai
        # Local generation is slow: allow long requests; retries rarely help a local server.
        return openai.AsyncOpenAI(base_url=_base_url(), api_key=_api_key(), timeout=1800, max_retries=1)

    # ------------------------------------------------------------- requests
    def _messages(self, system: str, messages: list[dict], model: str) -> list[dict]:
        if "qwen3" in model.lower():
            system += "\n\n/no_think"  # Qwen3's thinking mode makes every call several times slower
        return [{"role": "system", "content": system},
                *({"role": m["role"], "content": flatten(m["content"])} for m in messages)]

    def _options(self, model: str, effort: str | None, max_tokens: int) -> dict[str, Any]:
        cap = int(os.environ.get("JOB_MCP_LOCAL_MAX_TOKENS", "16000") or 16000)
        opts: dict[str, Any] = {"max_tokens": min(max_tokens, cap), "temperature": 0.2}
        if effort and effort != "none" and "gpt-oss" in model.lower():
            opts["reasoning_effort"] = effort
        return opts

    def _translate(self, exc: Exception) -> AIError:
        import openai
        if isinstance(exc, openai.APIConnectionError):
            return AIError("ai_unreachable", f"Could not reach the local model server at {_base_url()}. "
                           "Is LM Studio's server running with a model loaded?")
        if isinstance(exc, openai.APITimeoutError):
            return AIError("ai_unavailable", "The local model took too long. Try a smaller model or a shorter resume.")
        if isinstance(exc, openai.NotFoundError):
            return AIError("ai_model", f"The local server doesn't have model '{self.model()}' loaded. "
                           "Load it in LM Studio or set JOB_MCP_LOCAL_MODEL.")
        if isinstance(exc, openai.BadRequestError):
            return AIError("ai_bad_request", f"The local server rejected the request: {getattr(exc, 'message', exc)}")
        if isinstance(exc, openai.APIStatusError):
            return AIError("ai_unavailable", f"Local model server error ({exc.status_code}).")
        return AIError("ai_error", f"{type(exc).__name__}: {exc}")

    async def _structured_once(self, model_cls: type[BaseModel], *, system: str, messages: list[dict],
                               model: str, effort: str, max_tokens: int) -> tuple[str | None, str, str]:
        import openai
        client = self.client()
        try:
            resp = await client.chat.completions.create(
                model=model, messages=self._messages(system, messages, model),
                response_format={"type": "json_schema", "json_schema": {
                    "name": model_cls.__name__, "schema": strict_schema(model_cls), "strict": True}},
                **self._options(model, effort, max_tokens))
        except openai.APIError as exc:
            raise self._translate(exc) from exc
        used = getattr(resp, "model", None) or model
        choice = resp.choices[0] if resp.choices else None
        if choice is None:
            return None, "the server returned no answer", used
        if choice.finish_reason == "length":
            return None, "the response was cut off (raise the context length in LM Studio)", used
        text = _FENCE.sub("", choice.message.content or "").strip()
        return text, "", used

    async def stream_text(self, *, system: str, messages: list[dict], model: str | None = None,
                          effort: str | None = None, max_tokens: int = 4000) -> AsyncIterator[str]:
        import openai
        client = self.client()
        model = model or self.chat_model()
        try:
            stream = await client.chat.completions.create(
                model=model, messages=self._messages(system, messages, model), stream=True,
                **self._options(model, effort or self.effort("chat"), max_tokens))
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
        except openai.APIError as exc:
            raise self._translate(exc) from exc
