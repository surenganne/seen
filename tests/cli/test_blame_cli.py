"""`seen blame`: text and JSON on a scripted turn, and one-line exit-2 failures (never a traceback)."""

import json
import os
import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from seen_cli.main import app
from tests.conftest import git
from tests.provenance.scenarios import Scene, lines

cli = CliRunner()


def run(cwd: Path, *args: str) -> tuple[int, str, str]:
    old = os.getcwd()
    try:
        os.chdir(cwd)
        r = cli.invoke(app, ["blame", *args], catch_exceptions=False)
    finally:
        os.chdir(old)
    return r.exit_code, r.stdout, r.stderr


@pytest.fixture
def scene(tmp_path: Path) -> Scene:
    s = Scene(tmp_path, "blamed")
    with s.turn():
        s.write("calc.py", lines("calc", 4))
    s.commit("add calc")
    return s


def test_text_shows_blocks_headline_and_limit(scene: Scene) -> None:
    code, out, _ = run(scene.root, "calc.py")
    assert code == 0 and "1-4  agent  " in out and "add mul to calc" in out
    assert "agent 4 / human 0 / not observed 0" in out and "not a claim" in out
    assert lines("calc", 1).strip() not in out  # no line text


def test_json_has_enriched_blocks_and_no_line_text(scene: Scene) -> None:
    code, out, _ = run(scene.root, "calc.py", "--json")
    d = json.loads(out)
    b = d["blocks"][0]
    assert code == 0 and d["counts"]["agent"] == 4 and b["who"] == "agent" and b["headline"] == "add mul to calc"
    assert b["started_at"] and "skills" in b and "model" in b
    assert "compute_calc" not in out


def test_human_lines_are_separate(scene: Scene) -> None:
    scene.human_append("calc.py", lines("mine", 2))
    scene.commit("human")
    d = json.loads(run(scene.root, "calc.py", "--json")[1])
    assert [x["who"] for x in d["blocks"]] == ["agent", "human"] and d["counts"]["human"] == 2


def test_reason_is_shown_for_a_binary_file(scene: Scene) -> None:
    (scene.root / "b.bin").write_bytes(b"\0\1\2\n")
    scene.commit("bin")
    code, out, _ = run(scene.root, "b.bin")
    assert code == 0 and "binary" in out


def test_notebook_gets_one_note(scene: Scene) -> None:
    (scene.root / "n.ipynb").write_text('{"cells": []}\n')
    scene.commit("nb")
    code, out, err = run(scene.root, "n.ipynb")
    assert code == 0 and "Notebook" in out + err


def _fails(cwd: Path, *args: str) -> None:
    code, out, err = run(cwd, *args)
    assert code == 2, (out, err)
    assert "Traceback" not in out + err and len((out + err).strip().splitlines()) == 1


def test_no_head(scene: Scene) -> None:
    git(scene.root, "update-ref", "-d", "refs/heads/main")  # a recorded project whose HEAD no longer resolves
    _fails(scene.root, "calc.py")


def test_unrecorded_repo(tmp_path: Path) -> None:
    r = tmp_path / "empty"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    _fails(r, "a.py")


def test_reason_prints_no_clean_summary(scene: Scene) -> None:
    (scene.root / "b.bin").write_bytes(b"\0\1\2\n")
    scene.commit("bin")
    out = run(scene.root, "b.bin")[1]
    assert "No lines attributed: binary" in out and "not observed 0" not in out


def test_control_characters_never_reach_the_terminal(scene: Scene) -> None:
    from seen_core.db import ledger_session
    from seen_core.db.models import Change

    evil = "\x1b[31mred\x1b]0;x\x07 and a long enough sentence\x85 here."
    with ledger_session() as db:
        for c in db.scalars(sa.select(Change)):
            c.summary, c.model = evil, evil
        db.commit()
    code, out, err = run(scene.root, "calc.py")
    raw = (out + err).encode()
    assert code == 0 and b"red" in raw and not re.search(rb"[\x00-\x08\x0b-\x1f\x7f]|\xc2[\x80-\x9f]", raw)
    assert "\x1b" not in json.loads(run(scene.root, "calc.py", "--json")[1])["blocks"][0]["headline"]


def test_missing_at_rev(scene: Scene) -> None:
    _fails(scene.root, "nope.py")
    _fails(scene.root, "calc.py", "--rev", "HEAD~1")  # no such rev (one commit)


def test_untracked(scene: Scene) -> None:
    (scene.root / "u.py").write_text("x = 1\n")
    _fails(scene.root, "u.py")


def test_deleted(scene: Scene) -> None:
    git(scene.root, "rm", "-q", "calc.py")
    scene.commit("rm")
    _fails(scene.root, "calc.py")


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "-rf"])
def test_bad_path(scene: Scene, bad: str) -> None:
    _fails(scene.root, "--", bad)


def test_bad_rev(scene: Scene) -> None:
    _fails(scene.root, "calc.py", "--rev", "--output=x")
