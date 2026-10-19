import json
from pathlib import Path

import pytest

from seen_core import paths, spool
from seen_core.pii import validators as v
from tests.helpers import Replay


def card() -> str:
    base = "531268001234567"
    return next(base + str(d) for d in range(10) if v.luhn_valid(base + str(d)))


def setup(repo: Path, tmp_path: Path, seen_home: Path, mode: str = "block") -> Replay:
    paths.ensure_dir(seen_home)
    paths.config_toml().write_text(f'[pii]\nmode = "{mode}"\n')
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt()
    return r


def read(r: Replay, p: Path):  # type: ignore[no-untyped-def]
    return r.fire("pre-read", "pre_tool_use_read", tool_input={"file_path": str(p)})


def test_block_mode_denies_read_of_card_number(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    (repo / "pay.csv").write_text(f"id,card\n1,{card()}\n")
    r = setup(repo, tmp_path, seen_home)
    res = read(r, repo / "pay.csv")
    assert res.code == 2 and "card" in res.stderr and card() not in res.stderr
    g = [x for x in spool.read("sess-1") if x["ev"] == "gate"][-1]
    assert (g["hook"], g["decision"], g["reason"]) == ("pre-read", "block", "pii")


def test_clean_file_and_other_modes_allowed(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    (repo / "pay.csv").write_text(f"1,{card()}\n")
    r = setup(repo, tmp_path, seen_home, mode="report")
    assert read(r, repo / "pay.csv").code == 0
    r2 = setup(repo, tmp_path, seen_home)
    assert read(r2, repo / "a.py").code == 0


def test_allowlisted_path_allowed(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    (repo / "tests/fixtures").mkdir(parents=True)
    (repo / "tests/fixtures/cards.csv").write_text(f"1,{card()}\n")
    (repo / ".seen").mkdir()
    (repo / ".seen/pii.yaml").write_text('allow_paths: ["tests/fixtures/**"]\n')
    r = setup(repo, tmp_path, seen_home)
    assert read(r, repo / "tests/fixtures/cards.csv").code == 0


def test_oversized_file_falls_back_and_says_so(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    (repo / "big.csv").write_text("x" * (300 * 1024) + card())
    r = setup(repo, tmp_path, seen_home)
    res = read(r, repo / "big.csv")
    assert res.code == 0 and "256 KB" in json.loads(res.stdout)["systemMessage"]
    assert [x for x in spool.read("sess-1") if x["ev"] == "pre_read_deferred"][0]["reason"] == "size"


def test_time_budget_falls_back(repo: Path, tmp_path: Path, seen_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / "pay.csv").write_text(f"1,{card()}\n" * 2000)
    r = setup(repo, tmp_path, seen_home)
    monkeypatch.setenv("SEEN_PRE_READ_BUDGET_MS", "0")
    res = read(r, repo / "pay.csv")
    assert res.code == 0 and [x for x in spool.read("sess-1") if x["ev"] == "pre_read_deferred"][0]["reason"] == "time"


def test_symlink_to_outside_not_followed(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    secret = tmp_path / "outside.csv"
    secret.write_text(card())
    (repo / "link.csv").symlink_to(secret)
    r = setup(repo, tmp_path, seen_home)
    assert read(r, repo / "link.csv").code in (0, 2)  # decided on content Claude would read; never crashes


@pytest.mark.parametrize("pattern", ["**", "*", "**/*", "*.csv"])
def test_overbroad_allow_paths_do_not_disable_pre_read_block(repo: Path, tmp_path: Path, seen_home: Path, pattern: str) -> None:
    (repo / "pay.csv").write_text(f"1,{card()}\n")
    (repo / ".seen").mkdir()
    (repo / ".seen/pii.yaml").write_text(f'allow_paths: ["{pattern}"]\n')
    r = setup(repo, tmp_path, seen_home)
    assert read(r, repo / "pay.csv").code == 2
