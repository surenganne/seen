"""The test isolation cannot be lifted silently (monkeypatch.undo() reverts the seen_home fixture)."""

from __future__ import annotations

from pathlib import Path

import pytest

from seen_core import paths
from tests.conftest import REAL_HOME, assert_not_real_home
from tests.helpers import Replay


def test_home_is_refused_after_monkeypatch_undo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()
    with pytest.raises(AssertionError, match="outside the test tmp dir"):
        paths.home()
    with pytest.raises(AssertionError, match="outside the test tmp dir"):
        paths.ledger_db()


def test_home_is_refused_when_pointed_at_the_real_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEEN_HOME", str(REAL_HOME))
    with pytest.raises(AssertionError, match="outside the test tmp dir"):
        paths.home()


def test_builders_refuse_the_real_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert_not_real_home()  # the scratch home is fine
    monkeypatch.setenv("SEEN_HOME", str(REAL_HOME))
    with pytest.raises(RuntimeError, match="SEEN_HOME"):
        assert_not_real_home()
    monkeypatch.delenv("SEEN_HOME")  # unset means ~/.seen
    with pytest.raises(RuntimeError, match="SEEN_HOME"):
        Replay(tmp_path, tmp_path)
