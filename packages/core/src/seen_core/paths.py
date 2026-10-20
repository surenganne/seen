"""~/.seen layout. SEEN_HOME overrides the root (dev data, tests). Stdlib only."""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("SEEN_HOME") or "~/.seen").expanduser()


def ledger_db() -> Path:
    return home() / "ledger.db"


def audit_db() -> Path:
    return home() / "audit.db"


def audit_heads() -> Path:
    return home() / "audit-heads.log"


def secret_key() -> Path:
    return home() / "secret.key"


def config_toml() -> Path:
    return home() / "config.toml"


def spool_file(session_id: str) -> Path:
    return home() / "spool" / f"{_safe(session_id)}.jsonl"


def snap_file(session_id: str) -> Path:
    return home() / "snap" / f"{_safe(session_id)}.json"


def hook_log() -> Path:
    return home() / "log" / "hook.log"




def ensure_dir(p: Path) -> Path:
    """Create a Seen data dir as 0700: it holds prompts, ledger and keys."""
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    if p.is_relative_to(home()):
        for d in [p, *p.parents]:
            if d == home().parent:
                break
            os.chmod(d, 0o700)
    return p


def redact_home(path: str) -> str:
    h = os.path.expanduser("~")
    if h and (path == h or path.startswith(h + os.sep)):
        return "~" + path[len(h):]
    return path


def _safe(name: str) -> str:
    # session ids come from hook stdin; never let them escape the folder
    return "".join(c for c in name if c.isalnum() or c in "-_") or "unknown"
