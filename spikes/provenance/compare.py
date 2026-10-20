"""PV-0 spike: Method A (tool-input fingerprints) vs Method B (fingerprints of `git diff <head_before>` added lines).

Usage: uv run python spikes/provenance/compare.py
Deterministic: scratch git repos with real git, simulated tool inputs as plain dicts, no network, no Claude.
Scoring is per candidate line (spec section 4: >= 10 alphanumerics after normalising) in the final HEAD,
attributed through `git blame -w -M -C` at the path the blamed commit used. Trivial lines are not scored here
(the read side attributes them by adjacency, spec 6.3).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

KEY = b"spike-only-key"  # the product uses the per-install secret.key
TRIVIAL_MIN = 10
NONREPO = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def normalize(line: str) -> str:
    return " ".join(line.split())


def candidate(line: str) -> bool:
    return sum(c.isalnum() for c in normalize(line)) >= TRIVIAL_MIN


def fp(line: str) -> bytes:
    return hmac.new(KEY, b"seen-line-v1\0" + normalize(line).encode(), hashlib.sha256).digest()[:8]


def added_lines(tool: str, ti: dict) -> list[str]:
    """Spec section 5 table."""
    if tool == "Write":
        return ti["content"].splitlines()
    if tool == "NotebookEdit":
        return [] if ti.get("edit_mode") == "delete" else ti["new_source"].splitlines()
    edits = ti["edits"] if tool == "MultiEdit" else [ti]
    out: list[str] = []
    for e in edits:
        old = Counter(normalize(x) for x in e["old_string"].splitlines())
        for ln in e["new_string"].splitlines():
            if old[normalize(ln)] > 0:
                old[normalize(ln)] -= 1
            else:
                out.append(ln)
    return out


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.tick = 0
        self.a: set[tuple[str, bytes]] = set()  # Method A prints
        self.b: set[tuple[str, bytes]] = set()  # Method B prints
        self.truth: set[tuple[str, str]] = set()  # (path, normalised text) the agent wrote, as of now
        self.head_before: str | None = None
        root.mkdir()
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        self.tick += 1
        date = f"2026-10-01T00:{self.tick // 60:02d}:{self.tick % 60:02d}+0530"
        env = {**os.environ, **NONREPO, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        return subprocess.run(["git", "-c", "user.name=dev", "-c", "user.email=dev@example.com", *args],
                              cwd=self.root, env=env, check=True, capture_output=True, text=True).stdout

    def commit(self, msg: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def read(self, path: str) -> str:
        p = self.root / path
        return p.read_text() if p.exists() else ""

    def put(self, path: str, text: str) -> None:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    # --- a person ---
    def human_write(self, path: str, text: str) -> None:
        self.put(path, text)
        self.truth -= {(path, normalize(x)) for x in text.splitlines()}

    def human_replace(self, path: str, old: str, new: str) -> None:
        cur = self.read(path)
        assert old in cur, (path, old)
        self.put(path, cur.replace(old, new, 1))
        self.truth -= {(path, normalize(x)) for x in new.splitlines()}

    # --- the agent ---
    def begin_turn(self) -> None:
        self.head_before = self.git("rev-parse", "HEAD").strip()

    def tool(self, name: str, ti: dict) -> None:
        path = ti["file_path"]
        if name == "Write":
            self.put(path, ti["content"])
        else:
            cur = self.read(path)
            for e in ti["edits"] if name == "MultiEdit" else [ti]:
                assert e["old_string"] in cur
                cur = cur.replace(e["old_string"], e["new_string"], 1)
            self.put(path, cur)
        for ln in added_lines(name, ti):
            self.truth.add((path, normalize(ln)))
            if candidate(ln):
                self.a.add((path, fp(ln)))

    def bash_generated(self, path: str, text: str) -> None:
        """The agent ran a command that wrote this file: no tool input carries the text."""
        self.put(path, text)
        self.truth |= {(path, normalize(x)) for x in text.splitlines()}

    def end_turn(self) -> None:
        assert self.head_before
        diff = self.git("diff", "--unified=0", "--no-renames", "--end-of-options", self.head_before, "--")
        path = None
        for ln in diff.splitlines():
            if ln.startswith("+++ "):
                path = ln[6:] if ln.startswith("+++ b/") else None
            elif ln.startswith("+") and path and candidate(ln[1:]):
                self.b.add((path, fp(ln[1:])))
        for path in self.git("ls-files", "--others", "--exclude-standard").splitlines():
            self.b |= {(path, fp(x)) for x in self.read(path).splitlines() if candidate(x)}
        self.head_before = None

    # --- scoring ---
    def blame(self) -> list[tuple[str, str, str]]:
        """(current path, path at blamed commit, text) for every line in HEAD."""
        out: list[tuple[str, str, str]] = []
        for path in self.git("ls-files").splitlines():
            origin = path
            for ln in self.git("blame", "--line-porcelain", "-w", "-M", "-C", "HEAD", "--", path).splitlines():
                if ln.startswith("filename "):
                    origin = ln[9:]
                elif ln.startswith("\t"):
                    out.append((path, origin, ln[1:]))
        return out

    def score(self, prints: set[tuple[str, bytes]]) -> tuple[int, int, int]:
        tp = fp_ = fn = 0
        for path, origin, text in self.blame():
            if not candidate(text):
                continue
            pred = (origin, fp(text)) in prints
            true = (path, normalize(text)) in self.truth
            tp += pred and true
            fp_ += pred and not true
            fn += true and not pred
        return tp, fp_, fn


def lines(tag: str, n: int, start: int = 0) -> str:
    return "".join(f"{tag}_value_{i} = compute_{tag}({i}, factor={i * 7})\n" for i in range(start, start + n))


BASE = "def add(left, right):\n    return left + right\n"


def s_in_turn_commit(r: Repo) -> None:
    r.human_write("calc.py", BASE)
    r.commit("base")
    r.begin_turn()
    r.tool("Edit", {"file_path": "calc.py", "old_string": "    return left + right\n",
                    "new_string": "    return left + right\n\n\ndef multiply(left, right):\n    return left * right\n"})
    r.tool("Write", {"file_path": "util.py", "content": lines("agent", 8)})
    r.commit("agent commits in the turn")
    r.end_turn()


def s_human_commit_later(r: Repo) -> None:
    r.human_write("calc.py", BASE)
    r.commit("base")
    r.begin_turn()
    r.tool("Write", {"file_path": "util.py", "content": lines("agent", 8)})
    r.end_turn()
    r.put("util.py", r.read("util.py") + lines("human", 3))
    r.commit("person commits the next day")


def s_human_edits_half(r: Repo) -> None:
    r.human_write("calc.py", BASE)
    r.commit("base")
    r.begin_turn()
    r.tool("Write", {"file_path": "util.py", "content": lines("agent", 10)})
    for i in range(0, 10, 2):  # a person edits half the agent's lines while the turn runs
        r.human_replace("util.py", f"factor={i * 7})", f"factor={i * 7}, strict=True)")
    r.put("util.py", r.read("util.py") + lines("human", 4))
    r.end_turn()
    r.commit("mixed")


def s_squash_merge(r: Repo) -> None:
    r.human_write("calc.py", BASE)
    r.commit("base")
    r.git("checkout", "-q", "-b", "feature")
    r.begin_turn()
    r.tool("Write", {"file_path": "feat.py", "content": lines("agent", 6)})
    r.end_turn()
    r.commit("agent 1")
    r.put("feat.py", r.read("feat.py") + lines("human", 3))
    r.commit("person")
    r.begin_turn()
    r.tool("Edit", {"file_path": "feat.py", "old_string": "human_value_2 = compute_human(2, factor=14)\n",
                    "new_string": "human_value_2 = compute_human(2, factor=14)\n" + lines("agent", 4, start=6)})
    r.end_turn()
    r.commit("agent 2")
    r.git("checkout", "-q", "main")
    r.git("merge", "-q", "--squash", "feature")
    r.commit("squashed")


def s_rename(r: Repo) -> None:
    r.human_write("calc.py", BASE)
    r.commit("base")
    r.begin_turn()
    r.tool("Write", {"file_path": "old_name.py", "content": lines("agent", 8)})
    r.end_turn()
    r.commit("agent")
    r.git("mv", "old_name.py", "pkg_new_name.py")
    r.truth = {("pkg_new_name.py", t) if p == "old_name.py" else (p, t) for p, t in r.truth}
    r.put("pkg_new_name.py", r.read("pkg_new_name.py") + lines("human", 2))
    r.commit("person renames and adds")


def s_bash_generated(r: Repo) -> None:
    r.human_write("calc.py", BASE)
    r.commit("base")
    r.begin_turn()
    r.tool("Write", {"file_path": "gen.py", "content": lines("generator", 4)})
    r.bash_generated("table.py", lines("generated", 20))
    r.end_turn()
    r.commit("agent")


def s_human_only(r: Repo) -> None:
    r.human_write("calc.py", BASE)
    r.commit("base")
    r.human_write("util.py", lines("human", 12))
    r.commit("person")
    r.human_replace("util.py", "factor=0)", "factor=1)")
    r.commit("person again")


SCENARIOS = [("in-turn commit", s_in_turn_commit), ("human commit later", s_human_commit_later),
             ("human edits half", s_human_edits_half), ("squash merge", s_squash_merge), ("rename", s_rename),
             ("Bash-generated file", s_bash_generated), ("human-only repo", s_human_only)]


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "n/a"


def main() -> None:
    rows, a_bad = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (name, fn) in enumerate(SCENARIOS):
            r = Repo(Path(tmp) / f"s{i}")
            fn(r)
            (atp, afp, afn), (btp, bfp, bfn) = r.score(r.a), r.score(r.b)
            if atp + afp and atp / (atp + afp) < 0.99:
                a_bad.append(name)
            rows.append((name, pct(atp, atp + afp), pct(atp, atp + afn), pct(btp, btp + bfp), pct(btp, btp + bfn),
                         f"{atp}/{afp}/{afn}", f"{btp}/{bfp}/{bfn}"))
    head = ("scenario", "A prec", "A rec", "B prec", "B rec", "A tp/fp/fn", "B tp/fp/fn")
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for row in rows:
        print("| " + " | ".join(row) + " |")
    print("\nMethod A precision >= 99% in every scenario:", "yes" if not a_bad else f"NO ({', '.join(a_bad)})")


if __name__ == "__main__":
    main()
