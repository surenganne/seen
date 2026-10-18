"""Actor id: configured user id, else a hash of OS user + host (never the raw login). Stdlib only."""

from __future__ import annotations

import getpass
import hashlib
import socket

from . import config


def user_id() -> str:
    configured = str(config.load()["user"].get("id") or "")
    if configured:
        return configured
    try:
        raw = f"{getpass.getuser()}@{socket.gethostname()}"
    except Exception:
        raw = "unknown"
    return "u_" + hashlib.sha256(raw.encode()).hexdigest()[:12]
