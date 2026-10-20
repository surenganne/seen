"""`seen pr-report` data: diff parsing, range attribution, safe Markdown, gate. Scratch repos from scenarios.py."""

import dataclasses
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

from seen_core.db import ledger_session
from seen_core.db.models import Change, SkillInvocation
from seen_core.pii.checked import PII_CHECKED
from seen_core.provenance import report as rp
from tests.provenance.scenarios import Scene, lines
from tests.provenance.test_scenarios import SCENARIOS

DIFF = """diff --git a/old.py b/new.py
similarity index 90%
rename from old.py
rename to new.py
index 1111111..2222222 100644
--- a/old.py
+++ b/new.py
@@ -2,0 +3,2 @@ def f():
+x = 1
++++ b/forged.py
@@ -9 +10 @@
-gone = 1
+kept = 2
\\ No newline at end of file
diff --git a/img.png b/img.png
index 1111111..2222222 100644
Binary files a/img.png and b/img.png differ
diff --git a/dead.py b/dead.py
deleted file mode 100644
index 1111111..0000000
--- a/dead.py
+++ /dev/null
@@ -1,2 +0,0 @@
-a = 1
-b = 2
diff --git a/a b.py b/a b.py
new file mode 100644
--- /dev/null
+++ b/a b.py\t
@@ -0,0 +1 @@
+y = 3
"""


def test_parse_diff_added() -> None:
    assert rp.parse_diff_added(DIFF) == {"new.py": ["x = 1", "+++ b/forged.py", "kept = 2"], "a b.py": ["y = 3"]}


def test_parse_diff_added_empty() -> None:
    assert rp.parse_diff_added("") == {}


def _squash(tmp_path: Path) -> Scene:
    s = Scene(tmp_path, "squash")
    SCENARIOS["squash merge"](s)
    return s


def test_squashed_range_counts_add_up(tmp_path: Path) -> None:
    s = _squash(tmp_path)
    with ledger_session() as db:
        r = rp.build_report(db, s.project(), "HEAD~1", "HEAD")
    assert r.commits == 1 and r.added["agent"] == 10 and r.added["human"] == 3 and r.added["not_observed"] == 0
    total = int(s.git("diff", "--numstat", "HEAD~1", "HEAD").split()[0])
    assert sum(r.added.values()) + r.neutral == total == 13
    assert r.sessions == 1 and len(r.requests) == 2 and r.cost_usd is not None


def test_prompt_text_never_in_report(tmp_path: Path) -> None:
    s = _squash(tmp_path)
    with ledger_session() as db:
        for c in db.scalars(sa.select(Change)):
            c.summary = None  # fallback must not fall back to the prompt
            c.prompt_text = "SECRETPROMPT add mul to calc"
        db.commit()
        r = rp.build_report(db, s.project(), "HEAD~1", "HEAD")
    out = rp.render_md(r) + str(dataclasses.asdict(r))
    assert "SECRETPROMPT" not in out and "Changed 1 file in (root)" in out


def test_render_md(tmp_path: Path) -> None:
    s = _squash(tmp_path)
    with ledger_session() as db:
        r = rp.build_report(db, s.project(), "HEAD~1", "HEAD")
    md = rp.render_md(r)
    assert "agent 10" in md and "human 3" in md and "not observed 0" in md and "not observed" in md
    assert PII_CHECKED in md and "API-equivalent" in md
    assert "compute_agent" not in md and "compute_human" not in md  # no added-line text
    assert "API-equivalent" not in rp.render_md(dataclasses.replace(r, cost_usd=None))


def test_no_cost(tmp_path: Path) -> None:
    s = _squash(tmp_path)
    with ledger_session() as db:
        r = rp.build_report(db, s.project(), "HEAD~1", "HEAD", with_cost=False)
    assert r.cost_usd is None and "API-equivalent" not in rp.render_md(r)


EVIL = "@someone see [x](http://evil) <img src=x onerror=1> #12 `tick` with enough text."


def test_markdown_strings_only_inside_code_spans(tmp_path: Path) -> None:
    s = _squash(tmp_path)
    with ledger_session() as db:
        for c in db.scalars(sa.select(Change)):
            c.summary, c.model = EVIL, EVIL
        db.add(SkillInvocation(change_id=db.scalars(sa.select(Change.id)).first(), ordinal=9, skill_id=EVIL, status=EVIL))
        db.commit()
        r = rp.build_report(db, s.project(), "HEAD~1", "HEAD")
    r = dataclasses.replace(r, missed_rules=[EVIL], rules_missed=1)
    md = rp.render_md(r)
    import re
    stripped = re.sub(r"`[^`\n]*`", "", md)  # remove every code span
    for danger in ("@someone", "[x]", "<img", "#12", "evil"):
        assert danger in md and danger not in stripped, danger


def test_gate() -> None:
    r = rp.Report("b", "h", 1, {"agent": 1, "human": 0, "not_observed": 0}, [], 1, [], [("tdd", "approved")], 0, "none", PII_CHECKED, None)
    assert rp.gate(r, {"rule-missed", "pii-high", "unapproved-skill"}) == []
    bad = dataclasses.replace(r, rules_missed=1, pii_high=2, skills=[("x", "unreviewed")])
    assert len(rp.gate(bad, {"rule-missed", "pii-high", "unapproved-skill"})) == 3
    assert rp.gate(bad, set()) == [] and len(rp.gate(bad, {"rule-missed"})) == 1


@pytest.mark.parametrize("ref", ["--output=x", "a b", "", "x\0y"])
def test_unsafe_refs(tmp_path: Path, ref: str) -> None:
    s = _squash(tmp_path)
    with ledger_session() as db, pytest.raises(ValueError):
        rp.build_report(db, s.project(), ref, "HEAD")
    with ledger_session() as db, pytest.raises(ValueError):
        rp.build_report(db, s.project(), "HEAD", ref)


def test_unknown_ref(tmp_path: Path) -> None:
    s = _squash(tmp_path)
    with ledger_session() as db, pytest.raises(ValueError):
        rp.build_report(db, s.project(), "nope", "HEAD")


def test_pre_seen_range_is_not_observed(tmp_path: Path) -> None:
    s = Scene(tmp_path, "pre")
    s.pre("calc.py", lines("base", 3))
    with s.turn():
        s.write("other.py", lines("agent", 2))
    s.commit("agent")
    s.human_write("z.py", lines("zed", 4))
    s.commit("old person", when=int(time.time()) - 86_400 * 3)  # committed before the first recorded change
    with ledger_session() as db:
        r = rp.build_report(db, s.project(), "HEAD~1", "HEAD")
    assert r.added == {"agent": 0, "human": 0, "not_observed": 4}


@pytest.mark.perf
def test_fifty_file_range_under_3s(tmp_path: Path) -> None:
    s = Scene(tmp_path, "fifty")
    s.pre("calc.py", lines("base", 3))
    with s.turn():
        for i in range(50):
            s.write(f"m{i}.py", lines(f"f{i}", 20))
    s.commit("fifty")
    with ledger_session() as db:
        project = s.project()
        t = time.perf_counter()
        r = rp.build_report(db, project, "HEAD~1", "HEAD")
        took = time.perf_counter() - t
    assert r.added["agent"] == 1000 and took < 3
