"""Baseline subtraction (spec section 5): drop fingerprints of lines already in the file at the turn's start commit,
so a whole-file Write does not claim the person's unchanged lines. Not the hot path. Never stores or logs line text."""

from __future__ import annotations

from seen_core import gitutil
from seen_core.provenance import prints

MAX_BYTES = 1_000_000


def _baseline_fps(root: str | None, head: str | None, path: str, key: bytes) -> set[str]:
    """Hex fingerprints of the non-trivial lines of `path` at `head`; empty on any git problem or an over-cap file."""
    if not root or not head or head.startswith("-"):
        return set()
    try:
        text = gitutil.run_raw(root, "show", "--end-of-options", f"{head}:{path}")
        if text is None or len(text) > MAX_BYTES:
            return set()
        return {prints.fingerprint(s, key).hex() for s in text.splitlines() if not prints.is_trivial(s)}
    except Exception:  # ingest must never fail on a git problem
        return set()


def subtract(root: str | None, head: str | None, path: str, key: bytes, fps: list[str]) -> list[str]:
    """`fps` without those already present in the file at `head`."""
    if not fps:
        return fps
    base = _baseline_fps(root, head, path, key)
    return [f for f in fps if f not in base]
