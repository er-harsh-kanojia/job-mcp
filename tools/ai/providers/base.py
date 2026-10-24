"""Provider-neutral interface for the AI features.

Messages are passed in a neutral shape and converted by each provider:

    {"role": "user" | "assistant",
     "content": "text" | [{"type": "text", "text": "...", "cache": bool}, ...]}

``cache: True`` marks the end of a stable, reusable prefix (the resume). The
Anthropic provider turns it into a prompt-caching breakpoint; OpenAI caches
long shared prefixes automatically, so it just keeps the order.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Callable, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger("job_mcp.ai")

T = TypeVar("T", bound=BaseModel)


class AIError(RuntimeError):
    """An AI call failed in a way the caller should report (code + message)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class AINotConfigured(AIError):
    def __init__(self, provider_name: str = "the AI provider", env_key: str = "ANTHROPIC_API_KEY"):
        super().__init__("ai_not_configured",
                         f"{provider_name} is not set up. Put {env_key}=... in the .env file in the "
                         f"project folder and restart the app.")


def text_part(text: str, cache: bool = False) -> dict:
    return {"type": "text", "text": text, "cache": cache}


def parts_of(content: Any) -> list[dict]:
    if isinstance(content, str):
        return [text_part(content)]
    return [p if isinstance(p, dict) else text_part(str(p)) for p in content or []]


def flatten(content: Any) -> str:
    return "\n\n".join(p.get("text", "") for p in parts_of(content))


class Provider(ABC):
    id: str = ""
    name: str = ""          # "Claude (Anthropic)"
    short: str = ""         # "Claude"
    env_key: str = ""       # "ANTHROPIC_API_KEY"
    model_env: str = ""     # "JOB_MCP_ANTHROPIC_MODEL"
    chat_model_env: str = ""
    default_model: str = ""
    default_effort: str = "high"
    default_chat_effort: str = "low"

    def __init__(self) -> None:
        self._client: Any = None
        self._client_factory: Callable[[], Any] | None = None

    # --------------------------------------------------------------- config
    def is_configured(self) -> bool:
        return self._client_factory is not None or bool(os.environ.get(self.env_key, "").strip())

    def model(self) -> str:
        return os.environ.get(self.model_env, "").strip() or self.default_model

    def chat_model(self) -> str:
        return os.environ.get(self.chat_model_env, "").strip() or self.model()

    def effort(self, kind: str) -> str:
        env = f"JOB_MCP_{self.id.upper()}_{'CHAT_' if kind == 'chat' else ''}EFFORT"
        default = self.default_chat_effort if kind == "chat" else self.default_effort
        return os.environ.get(env, "").strip() or default

    def info(self) -> dict:
        return {"id": self.id, "name": self.name, "short": self.short,
                "configured": self.is_configured(), "model": self.model()}

    def not_configured(self) -> AINotConfigured:
        return AINotConfigured(self.name, self.env_key)

    def set_client_factory(self, factory: Callable[[], Any] | None) -> None:
        self._client_factory = factory
        self._client = None

    def client(self):
        if self._client_factory is not None:
            return self._client_factory()
        if not self.is_configured():
            raise self.not_configured()
        if self._client is None:
            self._client = self._make_client()
        return self._client

    @abstractmethod
    def _make_client(self) -> Any: ...

    # ----------------------------------------------------------- operations
    @abstractmethod
    async def _structured_once(self, model_cls: type[BaseModel], *, system: str, messages: list[dict],
                               model: str, effort: str, max_tokens: int) -> tuple[str | None, str, str]:
        """One request. Returns (json text or None, problem if None, model used)."""

    @abstractmethod
    def stream_text(self, *, system: str, messages: list[dict], model: str | None = None,
                    effort: str | None = None, max_tokens: int = 4000) -> AsyncIterator[str]:
        """Yield text deltas of one streamed reply."""

    async def structured(self, model_cls: type[T], *, system: str, messages: list[dict],
                         kind: str = "analysis", max_tokens: int = 32000,
                         check: Callable[[T], None] | None = None) -> tuple[T, str]:
        """JSON constrained to ``model_cls``'s schema, validated with pydantic, retried once.

        ``check`` may raise ValueError for semantic problems (also retried once).
        Returns (object, model used).
        """
        model = self.chat_model() if kind == "chat" else self.model()
        effort = self.effort(kind)
        problem = ""
        for attempt in (1, 2):
            text, problem_now, used = await self._structured_once(
                model_cls, system=system, messages=messages, model=model, effort=effort, max_tokens=max_tokens)
            if text is None:
                problem = problem_now
                log.warning("ai[%s]: structured output unusable (attempt %d): %s", self.id, attempt, problem)
                continue
            try:
                obj = model_cls.model_validate(json.loads(text))
                if check is not None:
                    check(obj)
                return obj, used
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                problem = f"{type(exc).__name__}: {str(exc)[:300]}"
                log.warning("ai[%s]: structured output failed validation (attempt %d): %s",
                            self.id, attempt, problem)
        raise AIError("ai_invalid_output", f"{self.short}'s answer did not match the expected format ({problem}).")
