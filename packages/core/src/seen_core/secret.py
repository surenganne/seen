"""Per-install secret key (~/.seen/secret.key, 0600). Keys PII fingerprints and actor ids.
Never synced. Stdlib only."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from . import paths


def key() -> bytes:
    f = paths.secret_key()
    try:
        data = f.read_bytes()
        if len(data) >= 32:
            return data
    except OSError:
        pass
    paths.ensure_dir(f.parent)
    data = secrets.token_bytes(32)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return data


def keyed(value: str, n: int = 16) -> str:
    return hmac.new(key(), value.encode(), hashlib.sha256).hexdigest()[:n]
