"""Platform adapter registry.

To add a platform (e.g. linkedin, wellfound, hirist):
  1. create ``tools/platforms/<name>.py`` with a ``PlatformAdapter`` subclass
  2. add one line to ``_ADAPTERS`` below: ``"<name>": "<module>:<ClassName>"``
It then appears in SUPPORTED_PLATFORMS, run.py, and the MCP server.
"""

from __future__ import annotations

import importlib

from .base import PlatformAdapter

# name -> "module:Class" (imported lazily so one broken adapter can't break the rest)
_ADAPTERS: dict[str, str] = {
    "naukri": "tools.platforms.naukri:NaukriAdapter",
    "instahyre": "tools.platforms.instahyre:InstahyreAdapter",
    "hirist": "tools.platforms.hirist:HiristAdapter",
}

# Known but not implemented yet (reported by list_platforms).
PLANNED_PLATFORMS: list[str] = ["linkedin", "wellfound", "indeed"]

SUPPORTED_PLATFORMS: list[str] = list(_ADAPTERS)


def register(name: str, target: str) -> None:
    """Register an adapter at runtime ("module:Class")."""
    _ADAPTERS[name] = target
    if name not in SUPPORTED_PLATFORMS:
        SUPPORTED_PLATFORMS.append(name)


def get_adapter_class(name: str) -> type[PlatformAdapter]:
    key = (name or "").strip().lower()
    if key not in _ADAPTERS:
        planned = " (planned, not implemented yet)" if key in PLANNED_PLATFORMS else ""
        raise KeyError(f"Unsupported platform '{name}'{planned}. "
                       f"Supported: {', '.join(SUPPORTED_PLATFORMS)}")
    module_name, cls_name = _ADAPTERS[key].split(":")
    cls = getattr(importlib.import_module(module_name), cls_name)
    return cls


def get_adapter(name: str, context=None) -> PlatformAdapter:
    return get_adapter_class(name)(context=context)


__all__ = ["PlatformAdapter", "SUPPORTED_PLATFORMS", "PLANNED_PLATFORMS",
           "get_adapter", "get_adapter_class", "register"]
