"""OpenAI (ChatGPT) provider, via the official ``openai`` SDK (Responses API).

* structured: ``responses.create`` with ``text.format`` = strict JSON schema
  built from the pydantic model (validated again with pydantic by the caller)
* chat: ``responses.stream`` text deltas (``response.output_text.delta``)
* reasoning effort via ``reasoning.effort`` (JOB_MCP_OPENAI_EFFORT /
  JOB_MCP_OPENAI_CHAT_EFFORT; "none" omits it, e.g. for non-reasoning models)
* OpenAI caches long shared prompt prefixes automatically; the resume comes
  first and ``prompt_cache_key`` keeps related requests on the same cache.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from pydantic import BaseModel

from .base import AIError, Provider, flatten

_STRIP_KEYS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
               "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems", "default"}
# model families that don't take a `reasoning` parameter
_NO_REASONING_PREFIXES = ("gpt-4", "gpt-3.5", "chatgpt-4o")
CACHE_KEY = "job-mcp-resume"


def strict_schema(model_cls: type[BaseModel]) -> dict:
    """Strict JSON schema (all properties required, no additional properties)
    without numeric/string constraints (pydantic validates those client-side)."""
    from openai.lib._pydantic import to_strict_json_schema

    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in _STRIP_KEYS}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node
    return strip(to_strict_json_schema(model_cls))


def _to_input(messages: list[dict]) -> list[dict]:
    return [{"role": m["role"], "content": flatten(m["content"])} for m in messages]


def _translate(exc: Exception) -> AIError:
    import openai
    if isinstance(exc, openai.AuthenticationError):
        return AIError("ai_auth", "The OpenAI API key was rejected. Check OPENAI_API_KEY in .env.")
    if isinstance(exc, openai.PermissionDeniedError):
        return AIError("ai_permission", "The OpenAI API key lacks permission for this model.")
    if isinstance(exc, openai.NotFoundError):
        return AIError("ai_model", f"OpenAI model not found; check JOB_MCP_OPENAI_MODEL. ({exc})")
    if isinstance(exc, openai.RateLimitError):
        return AIError("ai_rate_limited", "Rate limited (or out of quota) on the OpenAI API. Try again later.")
    if isinstance(exc, openai.BadRequestError):
        return AIError("ai_bad_request", f"OpenAI API rejected the request: {getattr(exc, 'message', exc)}")
    if isinstance(exc, openai.APIStatusError):
        return AIError("ai_unavailable", f"OpenAI API error ({exc.status_code}). Try again later.")
    if isinstance(exc, openai.APIConnectionError):
        return AIError("ai_unreachable", "Could not reach the OpenAI API (network).")
    return AIError("ai_error", f"{type(exc).__name__}: {exc}")


def _is_api_error(exc: Exception) -> bool:
    import openai
    return isinstance(exc, openai.APIError)


def _refusal(response: Any) -> str | None:
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) == "message":
            for c in getattr(item, "content", None) or []:
                if getattr(c, "type", None) == "refusal":
                    return getattr(c, "refusal", "") or "refused"
    return None


class OpenAIProvider(Provider):
    id = "openai"
    name = "ChatGPT (OpenAI)"
    short = "ChatGPT"
    env_key = "OPENAI_API_KEY"
    model_env = "JOB_MCP_OPENAI_MODEL"
    chat_model_env = "JOB_MCP_OPENAI_CHAT_MODEL"
    # Near-flagship GPT-6.1 model with structured outputs and reasoning effort
    # (developers.openai.com/api/docs/models, checked 2026-10). Use gpt-6-astra for
    # the flagship or gpt-6-luna for the cheapest.
    default_model = "gpt-6.1-sol"
    default_effort = "medium"
    default_chat_effort = "low"

    def _make_client(self):
        import openai
        return openai.AsyncOpenAI(max_retries=3)

    def _options(self, model: str, effort: str | None, max_tokens: int) -> dict[str, Any]:
        opts: dict[str, Any] = {"max_output_tokens": max_tokens, "store": False,
                                "prompt_cache_key": CACHE_KEY}
        if effort and effort != "none" and not model.startswith(_NO_REASONING_PREFIXES):
            opts["reasoning"] = {"effort": effort}
        return opts

    async def _structured_once(self, model_cls: type[BaseModel], *, system: str, messages: list[dict],
                               model: str, effort: str, max_tokens: int) -> tuple[str | None, str, str]:
        client = self.client()
        try:
            resp = await client.responses.create(
                model=model, instructions=system, input=_to_input(messages),
                text={"format": {"type": "json_schema", "name": model_cls.__name__,
                                 "schema": strict_schema(model_cls), "strict": True}},
                **self._options(model, effort, max_tokens))
        except AIError:
            raise
        except Exception as exc:
            if _is_api_error(exc):
                raise _translate(exc) from exc
            raise
        used = getattr(resp, "model", None) or model
        if _refusal(resp) is not None:
            raise AIError("ai_refused", "ChatGPT declined this request.")
        if getattr(resp, "status", None) == "incomplete":
            return None, "the response was cut off (incomplete)", used
        return getattr(resp, "output_text", "") or "", "", used

    async def stream_text(self, *, system: str, messages: list[dict], model: str | None = None,
                          effort: str | None = None, max_tokens: int = 4000) -> AsyncIterator[str]:
        client = self.client()
        model = model or self.chat_model()
        try:
            async with client.responses.stream(
                model=model, instructions=system, input=_to_input(messages),
                **self._options(model, effort or self.effort("chat"), max_tokens),
            ) as stream:
                async for event in stream:
                    if getattr(event, "type", None) == "response.output_text.delta" and event.delta:
                        yield event.delta
                final = await stream.get_final_response()
        except AIError:
            raise
        except Exception as exc:
            if _is_api_error(exc):
                raise _translate(exc) from exc
            raise
        if _refusal(final) is not None:
            raise AIError("ai_refused", "ChatGPT declined this request.")
