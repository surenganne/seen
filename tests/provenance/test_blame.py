"""Blame parsing, the per-line rules (spec 6.2 to 6.5), path checks and caps. Fixtures: tests/provenance/fixtures/record.sh."""

from __future__ import annotations

import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from seen_core import audit, secret
from seen_core.db import ledger_session
from seen_core.db.models import Change, LinePrint, Project
from seen_core.db.models import Session as SessionRow
from seen_core.provenance import blame
from seen_core.provenance.blame import (
    BlameLine,
    Block,
    LineAttr,
    attribute,
    blocks,
    parse_porcelain,
    resolve_path,
)
from seen_core.provenance.prints import fingerprint
from tests.conftest import git

FX = Path(__file__).parent / "fixtures"
KEY = b"k" * 32


def load(name: str) -> list[BlameLine]:
    return parse_porcelain((FX / f"blame_{name}.txt").read_bytes().decode("utf-8", errors="surrogateescape"))  # as gitutil


# --- parse_porcelain -------------------------------------------------------------------------------------------------

def test_parse_porcelain_rename_uses_the_path_at_the_blamed_commit() -> None:
    ls = load("rename")
    assert [(x.n, x.path) for x in ls] == [(1, "old_name.py"), (2, "old_name.py"), (3, "new_name.py"), (4, "new_name.py")]
    assert ls[0].commit.startswith("7aae06ec") and ls[0].commit_time == 1790000000
    assert ls[2].commit.startswith("b2701e5d") and ls[3].commit_time == 1790000100
    assert ls[1].text == "    return alpha + 1"


def test_parse_porcelain_boundary_commit() -> None:
    ls = load("boundary")
    assert len(ls) == 4
    assert {(x.commit[:8], x.commit_time, x.path) for x in ls} == {("b2701e5d", 1790000100, "new_name.py")}


def test_parse_porcelain_repeated_commit_without_metadata() -> None:
    ls = load("interleaved")  # the third line's header carries no filename or time: the parser remembers them
    assert [(x.commit[:8], x.commit_time, x.path) for x in ls] == [
        ("f759446c", 1790000300, "inter.py"), ("272718f3", 1790000400, "inter.py"), ("f759446c", 1790000300, "inter.py")]


def test_parse_porcelain_path_with_spaces_and_quotes() -> None:
    (ln,) = load("quoted_path")
    assert ln.path == 'my "odd" file.py'
    assert ln.text == 'spaced_and_quoted = "value one"'


def test_parse_porcelain_crlf_text() -> None:
    ls = load("crlf")
    assert [x.text for x in ls] == ["line_with_crlf_ending = 1", "second_crlf_line_here = 2"]
    assert fingerprint(ls[0].text + "\r", KEY) == fingerprint("line_with_crlf_ending = 1", KEY)


def test_parse_porcelain_undecodable_bytes_are_replaced() -> None:
    ls = load("bytes")
    assert [x.text for x in ls] == ["caf�_latin1_bytes = 1", "plain_ascii_line_here = 2"]
    fingerprint(ls[0].text, KEY)  # no exception


def test_parse_porcelain_rejects_unexpected_structure() -> None:
    assert parse_porcelain("") == []
    head = "b" * 40 + " 1 1 1\ncommitter-time soon\n"
    assert parse_porcelain(head + "\tok\n") == [BlameLine(1, "b" * 40, 0, "", "ok")]
    for bad in ("\tstray text before any header\n", "not a header\n", "a" * 40 + " 1 x\n\tbad numbers\n",
                head + "\tok\n" + "b" * 40 + " 2 9\n\tline numbers jump\n",  # final line 9 after 1
                head + "\tok\nfilename injected.py\n\tforged\n",  # content line not right after its header group
                head):  # a header with no content line
        with pytest.raises(ValueError):
            parse_porcelain(bad)
    assert blame.unquote('"caf\\303\\251 \\t\\"x\\""') == 'caf\u00e9 \t"x"'
    assert blame.unquote('"bad \\') == '"bad \\'


# --- attribute -------------------------------------------------------------------------------------------------------

AG1 = "agent_value_one = compute(1)"
AG2 = "agent_value_two = compute(2)"


def bl(n: int, text: str, commit: str = "c1", t: int = 1000, path: str = "a.py") -> BlameLine:
    return BlameLine(n, commit, t, path, text)


def idx(*entries: tuple[str, str, list[tuple[str, float]]]) -> blame.Index:
    return {(p, fingerprint(t, KEY)): v for p, t, v in entries}


def who(lines: list[BlameLine], index: blame.Index, first: float | None = None,
        gaps: list[tuple[float, float]] | None = None) -> list[tuple[str, str | None]]:
    return [(a.who, a.change_id) for a in attribute(lines, index, KEY, first_change_at=first, gaps=gaps or [])]


def test_attribute_rules() -> None:
    index = idx(("a.py", AG1, [("ch1", 900.0)]), ("a.py", AG2, [("ch1", 900.0)]))
    # a matching fingerprint is agent; no match is human; the path is part of the key
    assert who([bl(1, AG1), bl(2, "human_typed_this = 1")], index) == [("agent", "ch1"), ("human", None)]
    assert who([bl(1, AG1, path="b.py")], index) == [("human", None)]
    assert attribute([bl(7, AG1)], index, KEY, first_change_at=None, gaps=[]) == [LineAttr(7, "agent", "ch1")]
    # several changes: the greatest ended_at not after the commit, else the earliest after it
    many = idx(("a.py", AG1, [("old", 500.0), ("new", 900.0), ("late", 1500.0)]))
    assert who([bl(1, AG1, t=1000)], many) == [("agent", "new")]
    after = idx(("a.py", AG1, [("x", 1500.0), ("y", 1200.0)]))
    assert who([bl(1, AG1, t=1000)], after) == [("agent", "y")]
    # trivial lines go by adjacency in the same blamed commit and change; blank lines are neutral
    assert who([bl(1, AG1), bl(2, "    }"), bl(3, ""), bl(4, "else:"), bl(5, AG2)], index) == [
        ("agent", "ch1"), ("agent", "ch1"), ("neutral", None), ("agent", "ch1"), ("agent", "ch1")]
    assert who([bl(1, AG1), bl(2, "}", commit="c2"), bl(3, AG2)], index)[1] == ("human", None)  # other commit
    assert who([bl(1, AG1), bl(2, "}"), bl(3, AG2, commit="c2")], index)[1] == ("human", None)  # neighbour elsewhere
    assert who([bl(1, AG1), bl(2, "}")], index)[1] == ("human", None)  # nothing below
    assert who([bl(1, AG1), bl(2, "}"), bl(3, "human_typed_this = 1")], index)[1] == ("human", None)
    two = idx(("a.py", AG1, [("ch1", 900.0)]), ("a.py", AG2, [("ch2", 950.0)]))
    assert who([bl(1, AG1), bl(2, "}"), bl(3, AG2)], two)[1] == ("human", None)  # different changes
    # not observed: older than the first change, or inside a recorded gap window; blank stays neutral
    assert who([bl(1, "human_typed_this = 1"), bl(2, "}"), bl(3, AG1), bl(4, "")], index, first=2000.0) == [
        ("not_observed", None), ("not_observed", None), ("not_observed", None), ("neutral", None)]
    gap = [(900.0, 1100.0)]
    assert who([bl(1, "human_typed_this = 1"), bl(2, "}"), bl(3, AG1)], index, first=500.0, gaps=gap) == [
        ("not_observed", None), ("not_observed", None), ("agent", "ch1")]
    assert who([bl(1, "human_typed_this = 1", t=1200)], index, first=500.0, gaps=gap) == [("human", None)]


def test_attribute_threshold_lines() -> None:
    nine, ten = "va = 1234567", "val = 1234567"  # 9 and 10 alphanumerics
    index = idx(("a.py", ten, [("ch1", 900.0)]), ("a.py", AG1, [("ch1", 900.0)]))
    assert who([bl(1, ten)], index) == [("agent", "ch1")]  # a candidate: matched by its own fingerprint
    assert who([bl(1, nine)], idx(("a.py", nine, [("ch1", 900.0)]))) == [("human", None)]  # trivial: never looked up
    assert who([bl(1, AG1), bl(2, nine), bl(3, ten)], index)[1] == ("agent", "ch1")


def test_blocks_merge_consecutive_lines() -> None:
    attrs = [LineAttr(1, "agent", "a"), LineAttr(2, "agent", "a"), LineAttr(3, "agent", "b"), LineAttr(4, "human", None),
             LineAttr(5, "human", None), LineAttr(6, "neutral", None), LineAttr(7, "human", None)]
    assert blocks(attrs) == [Block(1, 2, "agent", "a"), Block(3, 3, "agent", "b"), Block(4, 5, "human", None),
                             Block(6, 6, "neutral", None), Block(7, 7, "human", None)]
    assert blocks([]) == []


# --- resolve_path ----------------------------------------------------------------------------------------------------

def test_resolve_path_refuses_escape(tmp_path: Path) -> None:
    root, outside = tmp_path / "r", tmp_path / "outside"
    (root / "sub").mkdir(parents=True)
    outside.mkdir()
    (root / "a.py").write_text("x\n")
    (outside / "x.py").write_text("x\n")
    os.symlink(outside / "x.py", root / "link.py")
    os.symlink(outside, root / "linkdir")
    os.symlink(root / "a.py", root / "inner.py")
    for bad in ("../x", "/etc/passwd", "-n", "link.py", "linkdir/x.py", "sub/../../x", "./sub/../a.py", "", "a\0b", ".", "inner.py"):
        with pytest.raises(ValueError):
            resolve_path(str(root), bad)
    assert resolve_path(str(root), "a.py") == "a.py"
    assert resolve_path(str(root), "./a.py") == "a.py"
    assert resolve_path(str(root), "sub/deleted_locally.py") == "sub/deleted_locally.py"  # may exist only at the rev


# --- blame_file ------------------------------------------------------------------------------------------------------

def project(repo: Path) -> Project:
    return Project(id="p1", root_path=str(repo))


def commit_all(repo: Path, msg: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)


def test_blame_file_counts_and_blocks(repo: Path) -> None:
    with ledger_session() as db:
        fp = blame.blame_file(db, project(repo), "a.py")
    # no recorded change in the project: Seen saw none of it
    assert fp.counts == {"agent": 0, "human": 0, "not_observed": 2, "neutral": 0}
    assert fp.blocks == [Block(1, 2, "not_observed", None)]
    assert (fp.path, fp.rev, fp.truncated, fp.reason) == ("a.py", "HEAD", False, None)


def test_blame_file_refuses_bad_input(repo: Path) -> None:
    with ledger_session() as db:
        for rev in ("-n", "--output=/tmp/x", "HEAD:a.py", "a b", ""):
            with pytest.raises(ValueError):
                blame.blame_file(db, project(repo), "a.py", rev=rev)
        with pytest.raises(ValueError):
            blame.blame_file(db, project(repo), "../a.py")
        with pytest.raises(ValueError):
            blame.blame_file(db, Project(id="p1", root_path=None), "a.py")


def test_blame_file_caps(repo: Path) -> None:
    (repo / "big.txt").write_text("x" * 1_000_001)
    (repo / "bin.dat").write_bytes(b"abc\0def\n")
    (repo / "long.txt").write_text("line\n" * 20_001)
    commit_all(repo, "caps")
    (repo / "untracked.py").write_text("new file\n")
    with ledger_session() as db:
        got = {p: blame.blame_file(db, project(repo), p) for p in ("big.txt", "bin.dat", "long.txt", "untracked.py")}
    assert {p: f.reason for p, f in got.items()} == {"big.txt": "over 1 MB", "bin.dat": "binary",
                                                       "long.txt": "over 20,000 lines", "untracked.py": "not tracked at HEAD"}
    assert got["long.txt"].counts["not_observed"] == 20_001 and got["long.txt"].blocks == [Block(1, 20_001, "not_observed", None)]
    assert all(f.counts["agent"] == f.counts["human"] == 0 and not f.truncated for f in got.values())


def test_blame_file_timeout_is_truncated(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = blame.gitutil.run_raw

    def slow(cwd: str, *args: str, timeout: float = 10) -> str | None:
        if args[0] == "blame":
            time.sleep(timeout)  # what gitutil does on a timeout: the call returns None
            return None
        return real(cwd, *args, timeout=timeout)

    monkeypatch.setattr(blame.gitutil, "run_raw", slow)
    with ledger_session() as db:
        fp = blame.blame_file(db, project(repo), "a.py", budget_s=0.3)
    assert fp.truncated and fp.reason == "time budget exceeded" and fp.blocks == []


def test_blame_file_gap_windows(repo: Path) -> None:
    """A human commit inside a session with a capture.gap is not observed; one outside the window is human."""
    now = datetime.now(UTC)

    def iso(d: timedelta) -> str:
        return (now + d).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    with ledger_session() as db:
        db.add(Change(id="ch0", project_id="p1", session_id="s0", started_at=iso(timedelta(hours=-3)),
                      ended_at=iso(timedelta(hours=-3))))
        db.add(SessionRow(id="s1", project_id="p1", started_at=iso(timedelta(hours=-2)), ended_at=None))
        db.commit()
    audit.append([{"type": "capture.gap", "project_id": "p1", "session_id": "s1", "occurred_at": iso(timedelta(hours=-2))},
                  {"type": "tool.call", "project_id": "p1", "session_id": "s1", "occurred_at": iso(timedelta(hours=-1))},
                  {"type": "session.incomplete", "project_id": "p1", "session_id": "s1", "occurred_at": iso(timedelta(0))}])

    def commit_at(d: timedelta, line: str) -> None:
        with open(repo / "a.py", "a") as f:
            f.write(line + "\n")
        ts = f"{int((now + d).timestamp())} +0000"
        env = {"GIT_AUTHOR_DATE": ts, "GIT_COMMITTER_DATE": ts}
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", line, env=env)

    commit_at(timedelta(minutes=-90), "inside_the_gap_window = 1")
    commit_at(timedelta(minutes=-30), "after_the_gap_window = 1")  # after the last event other than session.incomplete
    with ledger_session() as db:
        fp = blame.blame_file(db, project(repo), "a.py")
    # lines 1-2 predate the first change (init commit, made now: so they are human, not pre-Seen)
    assert [(b.start, b.end, b.who) for b in fp.blocks] == [(1, 2, "human"), (3, 3, "not_observed"), (4, 4, "human")]


def test_blame_file_lone_cr_cannot_forge_lines(repo: Path) -> None:
    """Real git: a lone CR inside a committed line must not split it into a forged porcelain header."""
    forged = "agent_value_forged = compute(42)"
    payload = "real = 2\r" + "a" * 40 + " 1 9 1\rfilename injected_path.py\r\t" + forged
    (repo / "a.py").write_bytes(b"first_real_line_here = 1\n" + payload.encode() + b"\nthird_real_line_here = 3\n")
    commit_all(repo, "lone CR")
    out = blame.gitutil.run_raw(str(repo), "blame", "--porcelain", "-w", "-M", "-C", "HEAD", "--", "a.py")
    assert out is not None
    got = parse_porcelain(out)
    assert [(x.n, x.path) for x in got] == [(1, "a.py"), (2, "a.py"), (3, "a.py")]
    assert got[1].text == payload
    with ledger_session() as db:
        db.add(Change(id="ch0", project_id="p1", started_at="2000-01-01T00:00:00.000Z", ended_at="2000-01-01T00:00:00.000Z"))
        for path, text in (("injected_path.py", forged), ("a.py", forged)):
            db.add(LinePrint(project_id="p1", path=path, fp=fingerprint(text, secret.key()), change_id="ch0"))
        db.commit()
        fp = blame.blame_file(db, project(repo), "a.py")
    assert fp.counts == {"agent": 0, "human": 3, "not_observed": 0, "neutral": 0}
    assert fp.reason is None


def test_blame_file_line_cap_counts_lf_only(repo: Path) -> None:
    (repo / "cr.txt").write_bytes(b"x\r" * 25_000 + b"\n")  # one line for git, 25,001 after newline translation
    commit_all(repo, "cr only")
    with ledger_session() as db:
        fp = blame.blame_file(db, project(repo), "cr.txt")
    assert fp.reason is None and sum(fp.counts.values()) == 1


def test_blame_file_unparseable_output(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = blame.gitutil.run_raw

    def junk(cwd: str, *args: str, timeout: float = 10) -> str | None:
        return "not porcelain\n" if args[0] == "blame" else real(cwd, *args, timeout=timeout)

    monkeypatch.setattr(blame.gitutil, "run_raw", junk)
    with ledger_session() as db:
        fp = blame.blame_file(db, project(repo), "a.py")
    assert fp.reason == "unparseable blame output" and fp.blocks == [Block(1, 2, "not_observed", None)]


def test_blame_file_does_not_run_textconv_drivers(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    git(repo, "config", "diff.evil.textconv", f"touch {marker}; cat")
    git(repo, "config", "diff.evil.command", f"touch {marker}; true")
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("a.py diff=evil\n")
    (repo / "a.py").write_text("one\ntwo\nthree_is_longer_line = 3\n")
    commit_all(repo, "more")
    blame.gitutil.filter_overrides.cache_clear()
    with ledger_session() as db:
        fp = blame.blame_file(db, project(repo), "a.py")
    assert not marker.exists()
    assert sum(fp.counts.values()) == 3 and fp.reason is None


def test_pre_seen_cutoff_is_whole_seconds() -> None:
    assert who([bl(1, "human_typed_this = 1", t=1000)], {}, first=1000.7) == [("human", None)]
    assert who([bl(1, "human_typed_this = 1", t=999)], {}, first=1000.7) == [("not_observed", None)]


def test_blame_file_pins_output_encoding_against_hostile_config(repo: Path) -> None:
    git(repo, "config", "i18n.logOutputEncoding", "ISO-8859-1")
    git(repo, "config", "i18n.commitEncoding", "ISO-8859-1")
    (repo / "a.py").write_text("one\ntwo\nthree_is_longer_line = 3\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "non-ascii author", env={"GIT_AUTHOR_NAME": "Zoë Ünïcode 日本"})
    blame.gitutil.filter_overrides.cache_clear()
    with ledger_session() as db:
        fp = blame.blame_file(db, project(repo), "a.py")
    assert fp.reason is None and sum(fp.counts.values()) == 3


def test_blame_file_line_count_mismatch_fails_closed(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = blame.parse_porcelain
    monkeypatch.setattr(blame, "parse_porcelain", lambda out: real(out)[:-1])  # one line missing
    with ledger_session() as db:
        fp = blame.blame_file(db, project(repo), "a.py")
    assert fp.reason == "unparseable blame output" and fp.blocks == [Block(1, 2, "not_observed", None)]


def test_parse_porcelain_rejects_nul_in_a_header() -> None:
    sha = "a" * 40
    with pytest.raises(ValueError):
        parse_porcelain(f"{sha} 1 1 1\nauthor x\0y\nfilename a.py\n\tcode_line_one\n")


def _spy_git(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Every argv that reaches git through gitutil.run or gitutil.run_raw, so the checks below cannot pass vacuously if
    blame moves from one to the other."""
    seen: list[tuple[str, ...]] = []
    real_raw, real_run = blame.gitutil.run_raw, blame.gitutil.run

    def raw(cwd: str | Path, *args: str, timeout: float = 10) -> str | None:
        seen.append(args)
        return real_raw(cwd, *args, timeout=timeout)

    def run(cwd: str | Path, *args: str, timeout: float = 10) -> str | None:
        seen.append(args)
        return real_run(cwd, *args, timeout=timeout)

    monkeypatch.setattr(blame.gitutil, "run_raw", raw)
    monkeypatch.setattr(blame.gitutil, "run", run)
    return seen


def test_blame_argv_has_no_end_of_options(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """git 2.39 (the Docker image) rejects --end-of-options in every position of `git blame` and prints usage; 2.54 accepts it,
    so host-only runs hide the break. ADR 0019."""
    seen = _spy_git(monkeypatch)
    with ledger_session() as db:
        fp = blame.blame_file(db, project(repo), "a.py")
    assert fp.reason is None
    (argv,) = [a for a in seen if "blame" in a]
    assert "--end-of-options" not in argv
    assert argv == ("blame", "--porcelain", "--no-textconv", "-w", "-M", "-C", "HEAD", "--", "a.py")


@pytest.mark.parametrize("rev,path", [("-n", "a.py"), ("HEAD", "-a.py")])
def test_blame_never_passes_a_dash_leading_value_to_git(repo: Path, monkeypatch: pytest.MonkeyPatch, rev: str, path: str) -> None:
    seen = _spy_git(monkeypatch)
    with ledger_session() as db, pytest.raises(ValueError):
        blame.blame_file(db, project(repo), path, rev)
    assert not seen  # no git call at all, through run or run_raw


def test_blame_guard_holds_when_earlier_checks_are_bypassed(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With resolve_path or REV patched to let a '-' value through, blame_file's own check still raises before any git call
    (checked on both gitutil.run and gitutil.run_raw)."""
    with monkeypatch.context() as m:
        seen = _spy_git(m)
        m.setattr(blame, "resolve_path", lambda root, p: "-a.py")
        with ledger_session() as db, pytest.raises(ValueError):
            blame.blame_file(db, project(repo), "a.py")
        assert not seen
    with monkeypatch.context() as m:
        seen = _spy_git(m)
        m.setattr(blame, "REV", re.compile(r".*"))
        with ledger_session() as db, pytest.raises(ValueError):
            blame.blame_file(db, project(repo), "a.py", "-n")
        assert not seen
