"""One version, everywhere: a release bumps these together or CI fails."""

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from seen_core import brand

ROOT = Path(__file__).resolve().parents[1]
PYPROJECTS = ["pyproject.toml", "packages/cli/pyproject.toml", "packages/core/pyproject.toml",
              "packages/local_server/pyproject.toml", "packages/team_server/pyproject.toml"]


def versions(root: Path) -> dict[str, str]:
    out = {p: tomllib.loads((root / p).read_text())["project"]["version"] for p in PYPROJECTS}
    out["plugin.json"] = json.loads((root / "plugin/.claude-plugin/plugin.json").read_text())["version"]
    return out


def test_every_version_matches_brand() -> None:
    assert set(versions(ROOT).values()) == {brand.VERSION}


def test_bump_script_updates_every_place(tmp_path: Path) -> None:
    for rel in [*PYPROJECTS, "plugin/.claude-plugin/plugin.json", "packages/core/src/seen_core/brand.py"]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    r = subprocess.run([sys.executable, str(ROOT / "scripts/bump_version.py"), "9.8.7", "--root", str(tmp_path), "--no-lock"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert set(versions(tmp_path).values()) == {"9.8.7"}
    assert 'VERSION = "9.8.7"' in (tmp_path / "packages/core/src/seen_core/brand.py").read_text()


def test_bump_script_rejects_a_non_release_version(tmp_path: Path) -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts/bump_version.py"), "v1", "--root", str(tmp_path), "--no-lock"],
                       capture_output=True, text=True)
    assert r.returncode != 0
