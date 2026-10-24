"""Facade over the selected AI provider (Anthropic or OpenAI).

Keys come only from the environment or ``.env`` at the project root:
ANTHROPIC_API_KEY, OPENAI_API_KEY. Models: JOB_MCP_ANTHROPIC_MODEL,
JOB_MCP_OPENAI_MODEL (+ *_CHAT_MODEL, *_EFFORT, *_CHAT_EFFORT).
The prompts in review.py / interview.py are shared by both providers.
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator, Callable, TypeVar

from pydantic import BaseModel

from ..config import ROOT_DIR
from . import providers
from .providers import AIError, AINotConfigured, ProviderNotConfigured, text_part  # noqa: F401  (re-exports)

T = TypeVar("T", bound=BaseModel)

_env_loaded = False


def load_env() -> None:
    """Load ``.env`` from the project root once (real env vars win).

    Set JOB_MCP_NO_DOTENV=1 to skip (tests do).
    """
    global _env_loaded
    if _env_loaded or os.environ.get("JOB_MCP_NO_DOTENV", "").strip() in ("1", "true", "yes"):
        return
    _env_loaded = True
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(ROOT_DIR / ".env", override=False)


def provider() -> providers.Provider:
    return providers.selected()


def is_configured() -> bool:
    return provider().is_configured()


def require() -> providers.Provider:
    p = provider()
    if not p.is_configured():
        raise p.not_configured()
    return p


def set_client_factory(provider_id: str, factory: Callable[[], Any] | None) -> None:
    """Install a fake SDK client for one provider (tests)."""
    providers.get(provider_id).set_client_factory(factory)


async def structured(model_cls: type[T], *, system: str, messages: list[dict], kind: str = "analysis",
                     max_tokens: int = 32000, check: Callable[[T], None] | None = None) -> tuple[T, str]:
    return await require().structured(model_cls, system=system, messages=messages, kind=kind,
                                      max_tokens=max_tokens, check=check)


async def stream_text(*, system: str, messages: list[dict], max_tokens: int = 4000) -> AsyncIterator[str]:
    async for d in require().stream_text(system=system, messages=messages, max_tokens=max_tokens):
        yield d


async def complete_text(**kwargs) -> str:
    return "".join([d async for d in stream_text(**kwargs)])
