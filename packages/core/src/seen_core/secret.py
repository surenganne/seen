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
    # write a private temp file, then link it into place: link() fails if another process got there first, so the
    # key is created exactly once and nobody ever reads a half-written file
    tmp = f.with_name(f".{f.name}.{os.getpid()}.{secrets.token_hex(4)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    try:
        if f.exists() and len(f.read_bytes()) < 32:
            os.replace(tmp, f)  # a damaged file is replaced, not trusted
            return data
        os.link(tmp, f)
    except OSError:
        if not f.exists():
            os.replace(tmp, f)  # no hard links on this filesystem
        # else another process linked its key first (FileExistsError): read what is there
    finally:
        tmp.unlink(missing_ok=True)
    return f.read_bytes()


def keyed(value: str, n: int = 16) -> str:
    return hmac.new(key(), value.encode(), hashlib.sha256).hexdigest()[:n]
