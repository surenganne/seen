"""~/.seen/config.toml with defaults (plan 11B settings). Stdlib only: read by hooks."""

from __future__ import annotations

import copy
import tomllib
from typing import Any

from . import paths

DEFAULTS: dict[str, Any] = {
    "user": {"id": ""},
    "memory": {"inject": True, "gate": True, "budget_tokens": 1500},
    "skills": {"audit": True},
    "audit": {"retention_days": 365},
    "pii": {
        "mode": "report",  # off | report | warn | block
        "min_confidence": "medium",
        "types": ["email", "phone", "aadhaar", "pan", "card", "iban", "ssn", "upi", "dob", "secret", "ip", "gstin"],
        "scan_tool_results": True,
        "scan_diff": True,
        "store_prompt_text": "redacted",  # full | redacted | off
        "engine": "regex",  # regex | presidio
    },
    "sync": {"enabled": False, "server": "", "api_key_env": "SEEN_TEAM_API_KEY",
             "send_paths": False, "send_tokens": True, "send_cost": True, "send_skills": True,
             "send_pii_counts": False, "send_audit": False},
}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load() -> dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    f = paths.config_toml()
    if f.exists():
        try:
            _merge(cfg, tomllib.loads(f.read_text()))
        except (tomllib.TOMLDecodeError, OSError):
            pass  # a broken config must never break a hook; doctor reports it
    return cfg
