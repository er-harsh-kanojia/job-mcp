"""Config loading helpers.

config.json contains plaintext credentials. This module is the only place that
reads the file, and the public helpers never hand the credentials block to
callers (except ``get_login_email``, which returns only an e-mail address used to
prefill a login form). Never log or print anything from ``credentials``.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("job_mcp.config")

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.json"

_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_key: tuple[str, float] | None = None


def config_path() -> Path:
    """Path of the config file (override with the JOB_MCP_CONFIG env var)."""
    return Path(os.environ.get("JOB_MCP_CONFIG") or DEFAULT_CONFIG_PATH)


def _load_raw() -> dict[str, Any]:
    """Load config.json, re-reading it when the file changes on disk."""
    global _cache, _cache_key
    path = config_path()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        log.warning("Config file not found at %s; using empty profile", path)
        return {}
    key = (str(path), mtime)
    with _lock:
        if _cache is None or _cache_key != key:
            try:
                with open(path, encoding="utf-8") as fh:
                    _cache = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                # Do not include file contents in the message.
                log.warning("Could not parse config file %s: %s", path, type(exc).__name__)
                _cache = {}
            _cache_key = key
        return _cache


def get_profile() -> dict[str, Any]:
    """Candidate profile WITHOUT credentials (safe to pass around and log)."""
    raw = _load_raw()
    profile = {k: copy.deepcopy(v) for k, v in raw.items() if k != "credentials"}
    profile.setdefault("name", "")
    profile.setdefault("email", "")
    profile.setdefault("phone", "")
    profile.setdefault("location", "")
    profile.setdefault("resume_path", "")
    profile.setdefault("excluded_companies", get_excluded_companies())
    try:
        profile["experience_years"] = int(profile.get("experience_years") or 0)
    except (TypeError, ValueError):
        profile["experience_years"] = 0
    profile["autofill"] = get_autofill()
    return profile


def get_excluded_companies() -> list[str]:
    """List of company names to exclude from search results and applications."""
    raw = _load_raw()
    items = raw.get("excluded_companies") or []
    if not isinstance(items, list):
        return []
    return [str(x).strip() for x in items if str(x).strip()]


def get_autofill() -> dict[str, Any]:
    """The ``autofill`` block (CTC, notice period, per-skill experience, ...)."""
    autofill = copy.deepcopy(_load_raw().get("autofill") or {})
    autofill.setdefault("experience", {})
    autofill.setdefault("preferred_locations", [])
    return autofill


def get_experience_years(default: int = 0) -> int:
    try:
        return int(_load_raw().get("experience_years", default))
    except (TypeError, ValueError):
        return default


def get_skill_experience() -> dict[str, str]:
    """{skill (lowercase): years (string)} from autofill.experience."""
    exp = get_autofill().get("experience") or {}
    return {str(k).strip().lower(): str(v) for k, v in exp.items()}


def get_preferred_locations() -> list[str]:
    return [str(x) for x in (get_autofill().get("preferred_locations") or [])]


def get_login_email(platform: str) -> str:
    """E-mail to prefill on a login form (never the password).

    Falls back to the profile e-mail. Returns "" if nothing is configured.
    """
    raw = _load_raw()
    creds = (raw.get("credentials") or {}).get(platform) or {}
    email = creds.get("email") or raw.get("email") or ""
    return str(email)


def resume_path() -> Path | None:
    """Resume file path if configured and present on disk."""
    p = _load_raw().get("resume_path") or ""
    if not p:
        return None
    path = Path(os.path.expandvars(os.path.expanduser(str(p))))
    return path if path.is_file() else None


def data_dir() -> Path:
    """Directory for local data (DB, uploaded resume). Override with JOB_MCP_DATA_DIR."""
    return Path(os.environ.get("JOB_MCP_DATA_DIR") or (ROOT_DIR / "data"))


def invalidate_cache() -> None:
    global _cache, _cache_key
    with _lock:
        _cache = None
        _cache_key = None


def update_config(updates: dict[str, Any] | None = None,
                  autofill_updates: dict[str, Any] | None = None) -> None:
    """Merge profile changes into config.json and write it back atomically.

    * the ``credentials`` block is never read out, changed or removed
    * unknown keys (top level and inside ``autofill``) are preserved
    * ``autofill_updates`` is merged into ``autofill`` key by key (a value that is
      itself a dict, e.g. ``experience``, replaces the old dict)
    """
    path = config_path()
    with _lock:
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except FileNotFoundError:
            raw = {}
        # A config that exists but cannot be parsed is not overwritten (that
        # would destroy the credentials block): JSONDecodeError propagates.
        if not isinstance(raw, dict):
            raise ValueError("config.json must contain a JSON object")
        for k, v in (updates or {}).items():
            if k in ("credentials", "autofill"):
                continue
            raw[k] = v
        if autofill_updates:
            af = raw.get("autofill")
            if not isinstance(af, dict):
                af = {}
            for k, v in autofill_updates.items():
                af[k] = v
            raw["autofill"] = af
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(raw, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    invalidate_cache()
