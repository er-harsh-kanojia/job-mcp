"""Anthropic (Claude) provider, via the official ``anthropic`` SDK.

* structured: streamed Messages request with structured outputs
  (``output_config.format`` = JSON schema from the pydantic model)
* chat: streamed text deltas
* adaptive thinking is the model default; ``output_config.effort`` controls depth
* the resume prefix is a prompt-caching breakpoint (``cache_control``)
* ``fallbacks: "default"`` (server-side refusal fallback) on models that accept it;
  JOB_MCP_FALLBACKS=0 disables it
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

from pydantic import BaseModel

from .base import AIError, Provider, parts_of

_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# models that reject output_config.effort
_NO_EFFORT_PREFIXES = ("claude-haiku-4-5", "claude-sonnet-4-5", "claude-3")


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        blocks = []
        for p in parts_of(m["content"]):
            b: dict[str, Any] = {"type": "text", "text": p.get("text", "")}
            if p.get("cache"):
                b["cache_control"] = {"type": "ephemeral"}
            blocks.append(b)
        out.append({"role": m["role"], "content": blocks})
    return out


def _translate(exc: Exception) -> AIError:
    import anthropic
    if isinstance(exc, anthropic.AuthenticationError):
        return AIError("ai_auth", "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return AIError("ai_permission", "The Anthropic API key lacks permission for this model.")
    if isinstance(exc, anthropic.NotFoundError):
        return AIError("ai_model", f"Claude model not found; check JOB_MCP_ANTHROPIC_MODEL. ({exc})")
    if isinstance(exc, anthropic.RateLimitError):
        return AIError("ai_rate_limited", "Rate limited by the Claude API. Try again in a minute.")
    if isinstance(exc, anthropic.BadRequestError):
        return AIError("ai_bad_request", f"Claude API rejected the request: {getattr(exc, 'message', exc)}")
    if isinstance(exc, anthropic.APIStatusError):
        return AIError("ai_unavailable", f"Claude API error ({exc.status_code}). Try again later.")
    if isinstance(exc, anthropic.APIConnectionError):
        return AIError("ai_unreachable", "Could not reach the Claude API (network).")
    return AIError("ai_error", f"{type(exc).__name__}: {exc}")


def _is_api_error(exc: Exception) -> bool:
    import anthropic
    return isinstance(exc, anthropic.APIError)


def _text_of(message: Any) -> str:
    return "".join(getattr(b, "text", "") or "" for b in (getattr(message, "content", None) or [])
                   if getattr(b, "type", None) == "text")


class AnthropicProvider(Provider):
    id = "anthropic"
    name = "Claude (Anthropic)"
    short = "Claude"
    env_key = "ANTHROPIC_API_KEY"
    model_env = "JOB_MCP_ANTHROPIC_MODEL"
    chat_model_env = "JOB_MCP_ANTHROPIC_CHAT_MODEL"
    default_model = "claude-opus-5-5"
    # Claude Opus 5.5 defaults to medium effort; analysis is worth "high". The chat
    # uses the same model at "low" (fast, one cache namespace); set
    # JOB_MCP_ANTHROPIC_CHAT_MODEL (e.g. claude-sonnet-5-5) for a cheaper chat model.
    default_effort = "high"
    default_chat_effort = "low"

    def model(self) -> str:
        # JOB_MCP_MODEL is accepted as a legacy alias
        return (os.environ.get(self.model_env, "").strip() or os.environ.get("JOB_MCP_MODEL", "").strip()
                or self.default_model)

    def _make_client(self):
        import anthropic
        return anthropic.AsyncAnthropic(max_retries=3)

    def _options(self, model: str, effort: str | None) -> dict[str, Any]:
        opts: dict[str, Any] = {}
        if effort and effort != "none" and not model.startswith(_NO_EFFORT_PREFIXES):
            opts["output_config"] = {"effort": effort}
        if model in _FALLBACK_MODELS and os.environ.get("JOB_MCP_FALLBACKS", "1").strip() != "0":
            opts["betas"] = [_FALLBACK_BETA]
            opts["fallbacks"] = "default"
        return opts

    async def _structured_once(self, model_cls: type[BaseModel], *, system: str, messages: list[dict],
                               model: str, effort: str, max_tokens: int) -> tuple[str | None, str, str]:
        from anthropic import transform_schema
        client = self.client()
        opts = self._options(model, effort)
        opts.setdefault("output_config", {})["format"] = {"type": "json_schema",
                                                          "schema": transform_schema(model_cls)}
        try:
            async with client.beta.messages.stream(
                model=model, max_tokens=max_tokens, system=system,
                messages=_to_anthropic_messages(messages), **opts,
            ) as stream:
                final = await stream.get_final_message()
        except AIError:
            raise
        except Exception as exc:
            if _is_api_error(exc):
                raise _translate(exc) from exc
            raise
        used = getattr(final, "model", None) or model
        stop = getattr(final, "stop_reason", None)
        if stop == "refusal":
            raise AIError("ai_refused", "Claude declined this request.")
        if stop == "max_tokens":
            return None, "the response was cut off (max_tokens)", used
        return _text_of(final), "", used

    async def stream_text(self, *, system: str, messages: list[dict], model: str | None = None,
                          effort: str | None = None, max_tokens: int = 4000) -> AsyncIterator[str]:
        client = self.client()
        model = model or self.chat_model()
        opts = self._options(model, effort or self.effort("chat"))
        try:
            async with client.beta.messages.stream(
                model=model, max_tokens=max_tokens, system=system,
                messages=_to_anthropic_messages(messages), **opts,
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield text
                final = await stream.get_final_message()
        except AIError:
            raise
        except Exception as exc:
            if _is_api_error(exc):
                raise _translate(exc) from exc
            raise
        if getattr(final, "stop_reason", None) == "refusal":
            raise AIError("ai_refused", "Claude declined this request.")
