"""Acceptance 1 to 3 (spec section 10) on scratch repos driven through the real hook, plus the documented limits."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tests.provenance.scenarios import Scene, Score, lines

BASE = "def add(left, right):\n    return left + right\n"


def s_in_turn_commit(s: Scene) -> None:
    s.pre("calc.py", BASE)
    with s.turn():
        s.edit("calc.py", "    return left + right\n",
               "    return left + right\n\n\ndef multiply(left, right):\n    return left * right\n")
        s.write("util.py", lines("agent", 8))
        s.commit("agent commits in the turn")


def s_human_commit_later(s: Scene) -> None:
    s.pre("calc.py", BASE)
    with s.turn():
        s.write("util.py", lines("agent", 8))
    s.human_append("util.py", lines("human", 3))
    s.commit("person commits later")


def s_human_edits_half(s: Scene) -> None:
    s.pre("calc.py", BASE)
    with s.turn():
        s.write("util.py", lines("agent", 10))
        for i in range(0, 10, 2):  # a person edits half the agent's lines while the turn runs
            old = f"agent_value_{i} = compute_agent({i}, factor={i * 7})\n"
            s.human_replace("util.py", old, old.replace(")\n", ", strict=True)\n"))
        s.human_append("util.py", lines("human", 4))
    s.commit("mixed")


def s_squash_merge(s: Scene) -> None:
    s.pre("calc.py", BASE)
    s.git("checkout", "-q", "-b", "feature")
    with s.turn():
        s.write("feat.py", lines("agent", 6))
    s.commit("agent 1")
    s.human_append("feat.py", lines("human", 3))
    s.commit("person")
    with s.turn():
        anchor = "human_value_2 = compute_human(2, factor=14)\n"
        s.edit("feat.py", anchor, anchor + lines("agent", 4, start=6))
    s.commit("agent 2")
    s.git("checkout", "-q", "main")  # main has not moved, so after the squash it matches the model of feature
    s.git("merge", "-q", "--squash", "feature")
    s.commit("squashed")


def s_rename(s: Scene) -> None:
    s.pre("calc.py", BASE)
    with s.turn():
        s.write("old_name.py", lines("agent", 8))
    s.commit("agent")
    s.mv("old_name.py", "pkg_new_name.py")
    s.human_append("pkg_new_name.py", lines("human", 2))
    s.commit("person renames and adds")


def s_bash_generated(s: Scene) -> None:
    s.pre("calc.py", BASE)
    with s.turn():
        s.write("gen.py", lines("generator", 4))
        s.bash("table.py", lines("generated", 20))
    s.commit("agent")


def s_human_only(s: Scene) -> None:
    """Not vacuous: an agent turn writes another file first, so the ledger holds prints for this project."""
    s.pre("calc.py", BASE)
    with s.turn():
        s.write("other.py", lines("agent", 5))
    s.commit("agent writes another file")
    s.human_write("util.py", lines("human", 12))
    s.commit("person")
    s.human_replace("util.py", "human_value_0 = compute_human(0, factor=0)\n", "human_value_0 = compute_human(0, factor=1)\n")
    s.commit("person again")


def s_crlf(s: Scene) -> None:
    s.crlf.add("win.txt")
    s.pre("calc.py", BASE)
    with s.turn():
        s.write("win.txt", lines("agent", 6))
    s.commit("agent writes a CRLF file")
    s.human_append("win.txt", lines("human", 2))
    s.commit("person adds CRLF lines")


def s_threshold(s: Scene) -> None:
    """Lines at the trivial threshold: 9 alphanumerics are trivial, 10 are fingerprinted."""
    s.pre("calc.py", BASE)
    with s.turn():
        s.write("th.py", "alpha_value_one = compute(1)\nva = 1234567\nalpha_value_two = compute(2)\nval = 1234567\n"
                         "vb = 7654321\n")
    s.commit("agent")
    s.human_append("th.py", "human_value_one = compute(1)\nvc = 1111111\nhum = 2222222\n")
    s.commit("person")


SCENARIOS: dict[str, Callable[[Scene], None]] = {
    "in-turn commit": s_in_turn_commit, "human commit later": s_human_commit_later, "human edits half": s_human_edits_half,
    "squash merge": s_squash_merge, "rename": s_rename, "Bash-generated file": s_bash_generated,
    "human-only repo": s_human_only, "CRLF file": s_crlf, "threshold lines": s_threshold}


def run(tmp_path: Path, name: str) -> tuple[Scene, Score]:
    s = Scene(tmp_path, name.replace(" ", "-"))
    SCENARIOS[name](s)
    return s, s.score()


def test_scenarios(tmp_path: Path) -> None:
    total = Score()
    rows = []
    for name in SCENARIOS:
        _, sc = run(tmp_path, name)
        assert sc.bash_agent == 0, name  # Bash-generated lines never come out agent
        assert sc.pre_wrong == 0, name  # pre-Seen code is not observed
        total.tp, total.fp, total.fn = total.tp + sc.tp, total.fp + sc.fp, total.fn + sc.fn
        rows.append((name, sc))
        if name == "human-only repo":
            util = [w for _, _, w in sc.who["util.py"]]
            assert "agent" not in util and util.count("human") == 12
            assert sc.tp == 5  # the agent's other file is found, so prints exist
        if name == "Bash-generated file":
            assert {w for _, _, w in sc.who["table.py"]} == {"human"}
        if name == "threshold lines":
            assert [w for _, _, w in sc.who["th.py"]] == [
                "agent",  # candidate
                "agent",  # 9 alphanumerics, between two agent lines of the same change and commit
                "agent",  # candidate
                "agent",  # 10 alphanumerics: a candidate, matched by its own fingerprint
                "human",  # 9 alphanumerics at the edge of the agent block: missed (counts against recall)
                "human", "human", "human"]  # the person's lines, 9 and 10 alphanumerics included
    table = ", ".join(f"{n}: {sc.tp}/{sc.fp}/{sc.fn}" for n, sc in rows)  # tp/fp/fn, shown on failure
    assert total.tp / (total.tp + total.fp) >= 0.99, table
    assert total.tp / (total.tp + total.fn) >= 0.90, table


# --- documented limits (spec section 9); content-identical lines cannot be told apart, so these are agent -------------

def test_person_retypes_an_agent_line_exactly(tmp_path: Path) -> None:
    s = Scene(tmp_path, "retype")
    s.pre("calc.py", BASE)
    with s.turn():
        s.write("util.py", lines("agent", 4))
    s.commit("agent")
    line = "agent_value_1 = compute_agent(1, factor=7)\n"
    s.human_replace("util.py", line, "")
    s.commit("person deletes a line")
    s.human_replace("util.py", "agent_value_2 = compute_agent(2, factor=14)\n", line + "agent_value_2 = compute_agent(2, factor=14)\n")
    s.commit("person types it back")
    who = s.score().who["util.py"]
    assert who[1] == (line.strip(), "human", "agent")  # unavoidable: spec section 9


def test_agent_deletes_then_person_readds(tmp_path: Path) -> None:
    s = Scene(tmp_path, "readd")
    s.pre("calc.py", BASE)
    with s.turn():
        s.write("util.py", lines("agent", 4))
    s.commit("agent")
    line = "agent_value_3 = compute_agent(3, factor=21)\n"
    with s.turn():
        s.edit("util.py", line, "")  # deletes the line: adds no prints
    s.commit("agent deletes")
    s.human_append("util.py", line)
    s.commit("person re-adds the same text")
    sc = s.score()
    # outcome: agent, credited to the first change (the only one with that print). Same class as a retype.
    assert sc.who["util.py"][3] == (line.strip(), "human", "agent")


def test_duplicated_lines_in_one_file(tmp_path: Path) -> None:
    s = Scene(tmp_path, "dup")
    s.pre("calc.py", BASE)
    dup = "shared_setting_value = load_config(name)\n"
    with s.turn():
        s.write("util.py", dup + lines("agent", 3) + dup)  # the agent writes the same line twice: both agent
    s.commit("agent")
    s.human_append("util.py", lines("human", 2) + dup)  # a person adds a third copy: agent too (content-identical)
    s.commit("person")
    who = [(o, w) for _, o, w in s.score().who["util.py"]]
    assert who[0] == who[4] == ("agent", "agent")
    assert who[-1] == ("human", "agent")
    assert who[5:7] == [("human", "human"), ("human", "human")]


def test_agent_write_over_a_person_file_claims_its_unchanged_lines(tmp_path: Path) -> None:
    """Write fingerprints every line of `content` (spec section 5), so a Write that rewrites a person's file verbatim
    except one line makes the person's earlier, unchanged lines agent (rule 6.2.3: the earliest change after the commit)."""
    s = Scene(tmp_path, "rewrite")
    s.pre("calc.py", BASE)
    with s.turn():
        s.write("other.py", lines("agent", 2))
    s.commit("agent")
    s.human_write("util.py", lines("human", 4))
    s.commit("person")
    with s.turn():
        s.write("util.py", lines("human", 3) + "agent_rewritten_line = compute_agent(9)\n")
    s.commit("agent rewrites the file")
    who = [w for _, _, w in s.score().who["util.py"]]
    assert who == ["agent"] * 4
