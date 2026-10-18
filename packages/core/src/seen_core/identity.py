"""Actor id: a configured user id, else a keyed hash of OS user + host. Never a raw login
or email. Stdlib only."""

from __future__ import annotations

import getpass
import socket

from . import config, secret


def user_id() -> str:
    configured = str(config.load()["user"].get("id") or "")
    if configured and "@" not in configured:
        return configured
    if configured:  # looks like an email: pseudonymise it
        return "u_" + secret.keyed(configured.lower(), 12)
    try:
        raw = f"{getpass.getuser()}@{socket.gethostname()}"
    except Exception:
        raw = "unknown"
    return "u_" + secret.keyed(raw, 12)
