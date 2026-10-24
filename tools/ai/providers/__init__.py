"""AI provider registry and selection.

The selected provider is stored in config.json as ``"ai": {"provider": ...}``.
Selection rule: the stored choice if it has a key; otherwise whichever provider
has a key (Anthropic first); otherwise the stored choice / "anthropic".
"""

from __future__ import annotations

from ...config import get_profile, update_config
from .anthropic_provider import AnthropicProvider
from .base import AIError, AINotConfigured, Provider, flatten, parts_of, text_part
from .local_provider import LocalProvider
from .openai_provider import OpenAIProvider

PROVIDERS: dict[str, Provider] = {"anthropic": AnthropicProvider(), "openai": OpenAIProvider(),
                                  "local": LocalProvider()}
DEFAULT_PROVIDER = "anthropic"


class ProviderNotConfigured(AIError):
    def __init__(self, provider: Provider):
        msg = (provider.not_configured().message if provider.id == "local" else
               f"{provider.name} has no API key. Add {provider.env_key}=... to .env and restart.")
        super().__init__("provider_not_configured", msg)


def get(provider_id: str) -> Provider:
    try:
        return PROVIDERS[provider_id]
    except KeyError:
        raise KeyError(f"unknown AI provider '{provider_id}' (choose: {', '.join(PROVIDERS)})") from None


def stored_provider_id() -> str | None:
    ai = get_profile().get("ai")
    pid = ai.get("provider") if isinstance(ai, dict) else None
    return pid if pid in PROVIDERS else None


def selected_id() -> str:
    stored = stored_provider_id()
    if stored and PROVIDERS[stored].is_configured():
        return stored
    for pid in (DEFAULT_PROVIDER, *PROVIDERS):
        if PROVIDERS[pid].is_configured():
            return pid
    return stored or DEFAULT_PROVIDER


def selected() -> Provider:
    return PROVIDERS[selected_id()]


def select(provider_id: str) -> Provider:
    """Persist the choice in config.json (other keys and credentials untouched)."""
    p = get(provider_id)
    if not p.is_configured():
        raise ProviderNotConfigured(p)
    ai = get_profile().get("ai")
    ai = dict(ai) if isinstance(ai, dict) else {}
    ai["provider"] = provider_id
    update_config({"ai": ai})
    return p


def settings() -> dict:
    return {"provider": selected_id(), "providers": [p.info() for p in PROVIDERS.values()]}


__all__ = ["PROVIDERS", "Provider", "AIError", "AINotConfigured", "ProviderNotConfigured", "get",
           "selected", "selected_id", "select", "settings", "text_part", "parts_of", "flatten"]
