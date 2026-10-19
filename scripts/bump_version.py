"""Set one release version everywhere: brand.py, every pyproject.toml, plugin.json, then refresh uv.lock.

    uv run python scripts/bump_version.py 0.2.0          (then: commit, `git tag v0.2.0`, push the tag)
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PYPROJECTS = ["pyproject.toml", "packages/cli/pyproject.toml", "packages/core/pyproject.toml",
              "packages/local_server/pyproject.toml", "packages/team_server/pyproject.toml"]
BRAND = "packages/core/src/seen_core/brand.py"
PLUGIN = "plugin/.claude-plugin/plugin.json"


def sub_once(path: Path, pattern: str, repl: str) -> None:
    text = path.read_text()
    new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
    if n != 1:
        raise SystemExit(f"{path}: version line not found")
    path.write_text(new)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--no-lock", action="store_true", help="skip `uv lock`")
    a = ap.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        raise SystemExit("version must look like 1.2.3 (no leading v, no suffix)")
    for rel in PYPROJECTS:
        sub_once(a.root / rel, r'^version = "[^"]+"', f'version = "{a.version}"')
    sub_once(a.root / BRAND, r'^VERSION = "[^"]+"', f'VERSION = "{a.version}"')
    f = a.root / PLUGIN
    d = json.loads(f.read_text())
    d["version"] = a.version
    f.write_text(json.dumps(d, indent=2) + "\n")
    if not a.no_lock:
        subprocess.run(["uv", "lock"], cwd=a.root, check=True)
    print(f"Set {a.version} in {len(PYPROJECTS)} pyprojects, brand.py and plugin.json", file=sys.stderr)


if __name__ == "__main__":
    main()
