"""Line attribution from git blame (spec section 6). Read side: never stores or logs line text.

Repo files, refs and git config are untrusted: paths are checked by `resolve_path`, revs by a safe pattern, and git runs
only through `gitutil`, with `--end-of-options` (ADR 0019 has the argument order blame needs)."""

from __future__ import annotations

import math
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import sqlalchemy as sa

from .. import gitutil, paths, safeio, secret
from ..db.models import Change, LinePrint, Project, Session
from .prints import fingerprint, is_trivial, normalize

MAX_BYTES = 1_000_000
MAX_LINES = 20_000
Who = Literal["agent", "human", "not_observed", "neutral"]
WHO: tuple[Who, ...] = ("agent", "human", "not_observed", "neutral")
REASON_NOT_TRACKED = "not tracked"  # followed by " at <rev>"
REASON_BLAME_FAILED = "git blame failed"
REASON_UNPARSEABLE = "unparseable blame output"
Index = dict[tuple[str, bytes], list[tuple[str, float]]]  # (path, fp) -> [(change_id, ended_at epoch)]

_HEADER = re.compile(r"([0-9a-f]{40}|[0-9a-f]{64}) \d+ (\d+)(?: \d+)?")
_REV = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./~^@{}-]*")  # no leading '-', no ':', no spaces
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SURROGATE = re.compile("[\ud800-\udfff]")  # gitutil decodes with surrogateescape
_ESC = {b"a": 7, b"b": 8, b"t": 9, b"n": 10, b"v": 11, b"f": 12, b"r": 13, b'"': 34, b"\\": 92}


@dataclass(frozen=True)
class BlameLine:
    n: int
    commit: str
    commit_time: int
    path: str  # the file name at the blamed commit
    text: str


@dataclass(frozen=True)
class LineAttr:
    n: int
    who: Who
    change_id: str | None


@dataclass(frozen=True)
class Block:
    start: int
    end: int
    who: str
    change_id: str | None


@dataclass
class FileProvenance:
    path: str
    rev: str
    counts: dict[str, int]
    blocks: list[Block]
    truncated: bool
    reason: str | None


def is_failure(reason: str | None) -> bool:
    """True when there is nothing to show (as opposed to a file that is simply not line-attributed: binary, over a cap)."""
    return reason is not None and reason.startswith((REASON_NOT_TRACKED, REASON_BLAME_FAILED, REASON_UNPARSEABLE))


def _unquote(s: str) -> str:
    """git's C-style quoting of odd file names ("my \\"odd\\" file.py", octal escapes for bytes)."""
    if len(s) < 2 or s[0] != '"' or s[-1] != '"':
        return s
    try:
        raw = s[1:-1].encode(errors="surrogateescape")
    except UnicodeEncodeError:
        return s
    raw = re.sub(rb"\\([0-7]{3}|.)", lambda m: bytes([int(m[1], 8) & 255 if len(m[1]) == 3 else _ESC.get(m[1], m[1][0])]),
                 raw, flags=re.S)
    return raw.decode(errors="surrogateescape")


def parse_porcelain(out: str) -> list[BlameLine]:
    """`git blame --porcelain` output to lines. A commit's time and file name are printed only the first time it
    appears, so they are remembered per commit. Raises ValueError on structure it does not expect: final line numbers
    must run 1, 2, 3, ... and each content line must close the header group right before it (a forged line cannot hide
    in the stream). Unknown header keys are skipped."""
    body = out.removesuffix("\n")
    if not body:
        return []
    meta: dict[str, list[Any]] = {}  # commit -> [committer time, file name]
    res: list[BlameLine] = []
    cur, n = None, 0
    for ln in body.split("\n"):  # not splitlines(): a CR or form feed inside a line is part of its text
        if not ln.startswith("\t") and "\0" in ln:
            raise ValueError("NUL in a header line")
        if ln.startswith("\t"):
            if cur is None:
                raise ValueError("content line without a header")
            t, p = meta[cur]
            res.append(BlameLine(n, cur, t, p, _SURROGATE.sub("\ufffd", ln[1:].removesuffix("\r"))))
            cur = None
        elif cur is None:
            if (m := _HEADER.fullmatch(ln)) is None:
                raise ValueError("expected a header line")
            cur, n = m[1], int(m[2])
            if n != len(res) + 1:
                raise ValueError("line numbers out of order")
            meta.setdefault(cur, [0, ""])
        else:
            k, _, v = ln.partition(" ")
            if k == "committer-time" and v.isdecimal():
                meta[cur][0] = int(v)
            elif k == "filename":
                meta[cur][1] = _unquote(v)
    if cur is not None:
        raise ValueError("header without a content line")
    return res


def _pick(cands: list[tuple[str, float]], t: float) -> str:
    """Spec 6.2.3: the greatest ended_at not after the commit, else the earliest after it. Ties go by change id."""
    before = [c for c in cands if c[1] <= t]
    return max(before, key=lambda c: (c[1], c[0]))[0] if before else min(cands, key=lambda c: (c[1], c[0]))[0]


def attribute(lines: list[BlameLine], index: Index, key: bytes, *, first_change_at: float | None,
              gaps: list[tuple[float, float]]) -> list[LineAttr]:
    """Spec 6.2 to 6.4. A commit older than the first recorded change is not observed whatever matches (the agent
    Seen recorded cannot have typed it); a gap window turns only `human` into `not_observed`."""
    # whole seconds: a commit in the same second as the first change is not pre-Seen
    cutoff = None if first_change_at is None else first_change_at if math.isinf(first_change_at) else math.floor(first_change_at)
    trivial = [is_trivial(x.text) for x in lines]
    out: list[tuple[Who, str | None] | None] = []
    for x, triv in zip(lines, trivial, strict=True):
        if not normalize(x.text):
            out.append(("neutral", None))
        elif cutoff is not None and x.commit_time < cutoff:
            out.append(("not_observed", None))
        elif triv:
            out.append(None)  # decided by adjacency below
        elif cands := index.get((x.path, fingerprint(x.text, key))):
            out.append(("agent", _pick(cands, x.commit_time)))
        else:
            out.append(("human", None))
    above: list[int | None] = []
    last: int | None = None
    for i, triv in enumerate(trivial):
        above.append(last)
        last = last if triv else i
    below: list[int | None] = [None] * len(lines)
    last = None
    for i in range(len(lines) - 1, -1, -1):
        below[i] = last
        last = last if trivial[i] else i
    res = []
    for i, x in enumerate(lines):
        w: tuple[Who, str | None] = out[i] or ("human", None)
        if out[i] is None:  # trivial: agent only between two agent lines of the same change, in its own commit
            a, b = above[i], below[i]
            if a is not None and b is not None and lines[a].commit == lines[b].commit == x.commit:
                wa = out[a]
                if wa is not None and wa[0] == "agent" and wa == out[b]:
                    w = wa
        if w[0] == "human" and any(s <= x.commit_time <= e for s, e in gaps):
            w = ("not_observed", None)
        res.append(LineAttr(x.n, w[0], w[1]))
    return res


def blocks(attrs: list[LineAttr]) -> list[Block]:
    out: list[Block] = []
    for a in attrs:
        if out and (out[-1].who, out[-1].change_id, out[-1].end + 1) == (a.who, a.change_id, a.n):
            out[-1] = Block(out[-1].start, a.n, a.who, a.change_id)
        else:
            out.append(Block(a.n, a.n, a.who, a.change_id))
    return out


def _epoch(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def load_index(db: Any, project_id: str, paths: set[str]) -> Index:
    idx: Index = {}
    if not paths:
        return idx
    q = (sa.select(LinePrint.path, LinePrint.fp, LinePrint.change_id, Change.ended_at, Change.started_at)
         .join(Change, Change.id == LinePrint.change_id)
         .where(LinePrint.project_id == project_id, LinePrint.path.in_(sorted(paths))))
    for p, fp, cid, end, start in db.execute(q):
        idx.setdefault((p, bytes(fp)), []).append((cid, _epoch(end) or _epoch(start) or 0.0))
    return idx


def _gaps(db: Any, project_id: str) -> list[tuple[float, float]]:
    """Recorded gap windows: [session start, session end or its last audit event] for each session with a capture.gap
    or session.incomplete event. The incomplete marker itself is written by a later sweep, so its time is not the end."""
    try:
        con = sqlite3.connect(f"file:{paths.audit_db()}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT session_id, MIN(occurred_at), MAX(CASE WHEN type != 'session.incomplete' THEN occurred_at END), "
                "MAX(occurred_at) FROM audit_events WHERE project_id = ? AND session_id IN (SELECT session_id FROM "
                "audit_events WHERE project_id = ? AND type IN ('capture.gap', 'session.incomplete')) GROUP BY session_id",
                (project_id, project_id)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []  # no audit trail yet
    sess = {s.id: s for s in db.scalars(sa.select(Session).where(Session.id.in_([r[0] for r in rows])))}
    out = []
    for sid, first, last, last_any in rows:
        s = sess.get(sid)
        start = _epoch(s.started_at if s else None) or _epoch(first)
        end = _epoch(s.ended_at if s else None) or _epoch(last or last_any)
        if start is not None and end is not None:
            out.append((start, end))
    return out


def resolve_path(root: str, rel: str) -> str:
    """A repo-relative path, as git wants it. Refuses '..', absolute paths, option-like names and any symlink on the way."""
    if not rel or "\0" in rel or rel.startswith("-") or os.path.isabs(rel) or ".." in rel.split("/"):
        raise ValueError("path must be repo-relative, without '..'")
    norm = os.path.normpath(rel)
    if norm == "." or norm.startswith("-"):
        raise ValueError("path must name a file")
    full = os.path.join(root, norm)
    try:
        safeio.check_no_symlinks(Path(full), Path(root))
    except OSError as e:
        raise ValueError("path goes through a symlink") from e
    real = os.path.realpath(root)
    if os.path.commonpath([real, os.path.realpath(full)]) != real:
        raise ValueError("path is outside the repo")
    return norm.replace(os.sep, "/")


def blame_file(db: Any, project: Project, path: str, rev: str = "HEAD", budget_s: float = 5.0) -> FileProvenance:
    """Per-line attribution of `path` at `rev`. Raises ValueError for an unsafe path or rev. Over budget, returns
    `truncated`; a file over the caps, binary or not tracked returns `reason` and only not-observed lines."""
    root = project.root_path
    if not root:
        raise ValueError("project has no repo root")
    if not _REV.fullmatch(rev):
        raise ValueError("unsafe rev")
    rel = resolve_path(root, path)
    deadline = time.monotonic() + budget_s

    def left() -> float:
        return max(deadline - time.monotonic(), 0.01)

    def done(attrs: list[LineAttr], truncated: bool = False, reason: str | None = None) -> FileProvenance:
        counts: dict[str, int] = {k: 0 for k in WHO}
        for a in attrs:
            counts[a.who] += 1
        return FileProvenance(rel, rev, counts, blocks(attrs), truncated, reason)

    def unseen(n: int, reason: str) -> FileProvenance:
        return done([LineAttr(i, "not_observed", None) for i in range(1, n + 1)], reason=reason)

    def failed(call: str | None) -> FileProvenance | None:
        if call is not None:
            return None
        return done([], True, "time budget exceeded") if time.monotonic() >= deadline else None

    ls = gitutil.run(root, "--literal-pathspecs", "ls-tree", "-z", "-l", "--end-of-options", rev, "--", rel, timeout=left())
    if r := failed(ls):
        return r
    parts = (ls or "").split("\0")[0].partition("\t")[0].split()
    if len(parts) != 4 or parts[1] != "blob" or not _SHA.fullmatch(parts[2]):
        return unseen(0, f"{REASON_NOT_TRACKED} at {rev}")
    if not parts[3].isdecimal() or int(parts[3]) > MAX_BYTES:
        return unseen(0, "over 1 MB")
    blob = gitutil.run_raw(root, "cat-file", "blob", parts[2], timeout=left())
    if r := failed(blob):
        return r
    if blob is None:
        return unseen(0, f"{REASON_NOT_TRACKED} at {rev}")
    if "\0" in blob[:8000]:
        return unseen(0, "binary")
    n = blob.count("\n") + (bool(blob) and not blob.endswith("\n"))  # '\n' only, as git numbers lines
    if n > MAX_LINES:
        return unseen(n, "over 20,000 lines")
    # run_raw: newline translation would turn a lone CR in the file into a porcelain line break (forged headers)
    out = gitutil.run_raw(root, "blame", "--porcelain", "--no-textconv", "-w", "-M", "-C", "--end-of-options", "--", rel, rev,
                          timeout=left())
    if r := failed(out):
        return r
    if out is None:
        return unseen(0, REASON_BLAME_FAILED)
    try:
        lines = parse_porcelain(out)
    except ValueError:
        return unseen(n, REASON_UNPARSEABLE)
    if len(lines) != n:  # fail closed: the stream does not describe the blob we counted
        return unseen(n, REASON_UNPARSEABLE)
    first = _epoch(db.scalar(sa.select(sa.func.min(Change.started_at)).where(Change.project_id == project.id)))
    index = load_index(db, project.id, {x.path for x in lines})
    attrs = attribute(lines, index, secret.key(), first_change_at=math.inf if first is None else first,
                      gaps=_gaps(db, project.id))
    return done(attrs)
