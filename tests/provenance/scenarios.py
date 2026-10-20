"""Scratch-repo builders for the provenance scenario suite (spec section 10).

Real git and the real hook (through `Replay`). Ground truth is an owner model per file line: who typed it ("pre" before
Seen, "human", "agent" through Edit/Write, "bash" through a command). It is kept by the builders below, not by
fingerprints or blame, so scoring checks the attribution against something independent of it."""

from __future__ import annotations

import math
import os
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import sqlalchemy as sa

from seen_core.db import ledger_session
from seen_core.db.models import Project
from seen_core.provenance.blame import blame_file
from seen_core.provenance.prints import normalize
from tests.conftest import git
from tests.helpers import Replay

Line = list[str]  # [text, owner]


def lines(tag: str, n: int, start: int = 0) -> str:
    return "".join(f"{tag}_value_{i} = compute_{tag}({i}, factor={i * 7})\n" for i in range(start, start + n))


@dataclass
class Score:
    tp: int = 0  # agent, typed by the agent
    fp: int = 0  # agent, typed by someone else
    fn: int = 0  # typed by the agent through Edit/Write, still at HEAD, not agent
    bash_agent: int = 0  # Bash-written lines marked agent (must stay 0)
    pre_wrong: int = 0  # pre-Seen lines not marked not_observed (must stay 0)
    who: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)  # path -> [(text, owner, who)]


class Scene:
    def __init__(self, tmp: Path, name: str) -> None:
        self.root = tmp / name
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        self.rp = Replay(self.root, tmp, sid=f"sess-{name}")
        self.files: dict[str, list[Line]] = {}
        self.crlf: set[str] = set()
        self.clock = math.ceil(time.time())
        self.started = False

    # --- files and commits ---
    def _render(self, path: str) -> None:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        nl = "\r\n" if path in self.crlf else "\n"
        p.write_bytes("".join(t + nl for t, _ in self.files[path]).encode())

    def _set(self, path: str, text: str, owner: str) -> None:
        self.files[path] = [[t, owner] for t in text.splitlines()]
        self._render(path)

    def _replace(self, path: str, old: str, new: str, owner: str) -> None:
        """Replace the first run of whole lines `old` by `new`. A line kept from `old` keeps its owner."""
        cur, olds = self.files[path], old.splitlines()
        i = next(i for i in range(len(cur)) if [t for t, _ in cur[i:i + len(olds)]] == olds)
        kept: dict[str, list[str]] = defaultdict(list)
        for t, o in cur[i:i + len(olds)]:
            kept[normalize(t)].append(o)
        repl = [[t, kept[normalize(t)].pop(0) if kept[normalize(t)] else owner] for t in new.splitlines()]
        self.files[path] = cur[:i] + repl + cur[i + len(olds):]
        self._render(path)

    def commit(self, msg: str, when: int | None = None) -> None:
        self.clock = max(self.clock + 1, math.ceil(time.time()))
        ts = f"{when if when is not None else self.clock} +0000"
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", msg, env={"GIT_AUTHOR_DATE": ts, "GIT_COMMITTER_DATE": ts})

    def git(self, *args: str) -> str:
        return git(self.root, *args)

    def mv(self, old: str, new: str) -> None:
        self.git("mv", old, new)
        self.files[new] = self.files.pop(old)

    # --- a person ---
    def pre(self, path: str, text: str) -> None:
        """Code from before Seen: committed a day before any recorded change."""
        self._set(path, text, "pre")
        self.commit("before seen", when=int(time.time()) - 86_400)

    def human_write(self, path: str, text: str) -> None:
        self._set(path, text, "human")

    def human_append(self, path: str, text: str) -> None:
        self.files.setdefault(path, []).extend([t, "human"] for t in text.splitlines())
        self._render(path)

    def human_replace(self, path: str, old: str, new: str) -> None:
        self._replace(path, old, new, "human")

    # --- the agent ---
    @contextmanager
    def turn(self) -> Iterator[None]:
        if not self.started:
            self.rp.start()
            self.started = True
        self.rp.prompt()
        yield
        self.rp.model_works()
        self.rp.stop()

    def write(self, path: str, text: str) -> None:
        self._set(path, text, "agent")
        content = text.replace("\n", "\r\n") if path in self.crlf else text
        self.rp.fire("post-tool", "post_tool_use_write", tool_input={"file_path": str(self.root / path), "content": content})

    def edit(self, path: str, old: str, new: str) -> None:
        self._replace(path, old, new, "agent")
        self.rp.fire("post-tool", "post_tool_use_edit",
                     tool_input={"file_path": str(self.root / path), "old_string": old, "new_string": new, "replace_all": False})

    def bash(self, path: str, text: str) -> None:
        """The agent ran a command that wrote the file: no tool input carries the text."""
        self._set(path, text, "bash")
        self.rp.fire("post-tool", "post_tool_use_bash", tool_input={"command": f"python gen.py > {path}"})

    # --- scoring ---
    def project(self) -> Project:
        with ledger_session() as db:
            return db.scalars(sa.select(Project).where(Project.root_path == os.path.realpath(self.root))).one()

    def score(self) -> Score:
        s, project = Score(), self.project()
        with ledger_session() as db:
            for path in self.git("ls-files", "-z").split("\0"):
                if not path:
                    continue
                fp = blame_file(db, project, path)
                assert not fp.truncated and fp.reason is None, (path, fp.reason)
                who = [b.who for b in fp.blocks for _ in range(b.start, b.end + 1)]
                model = self.files[path]
                head = self.git("show", f"HEAD:{path}").split("\n")[:-1]
                assert [normalize(h) for h in head] == [normalize(t) for t, _ in model], path  # model matches HEAD
                assert len(who) == len(model), path
                s.who[path] = [(t, o, w) for (t, o), w in zip(model, who, strict=True)]
                for (t, owner), w in zip(model, who, strict=True):
                    if not normalize(t):
                        assert w == "neutral"
                        continue
                    s.tp += w == "agent" and owner == "agent"
                    s.fp += w == "agent" and owner != "agent"
                    s.fn += w != "agent" and owner == "agent"
                    s.bash_agent += w == "agent" and owner == "bash"
                    s.pre_wrong += owner == "pre" and w != "not_observed"
        return s
