"""Versions, skew checks and the upgrade plan. Never on the hook path: it shells out and may use the network."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tomllib
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path

from alembic.script import ScriptDirectory

from . import audit, brand, paths

GITHUB_SPEC = "git+https://github.com/surenganne/seen#subdirectory=packages/cli"
TAGS_URL = "https://api.github.com/repos/surenganne/seen/tags?per_page=100"
_REL = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(s: str | None) -> tuple[int, int, int] | None:
    m = _REL.match(s or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def is_newer(candidate: str | None, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return bool(a and b and a > b)


def plugin_version() -> str | None:
    from .skills.scan import claude_dir

    f = claude_dir() / "plugins" / "installed_plugins.json"
    try:
        rows = json.loads(f.read_text())["plugins"][f"{brand.PLUGIN}@{brand.MARKETPLACE}"]
        return str(rows[0]["version"])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def _scripts() -> ScriptDirectory:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "db" / "alembic"))
    return ScriptDirectory.from_config(cfg)


def schema_head() -> str:
    return str(_scripts().get_current_head())


def ledger_revision() -> str | None:
    db = paths.ledger_db()
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            row = con.execute("select version_num from alembic_version").fetchone()
        finally:
            con.close()
        return str(row[0]) if row else None
    except sqlite3.Error:
        return None


def hook_version(hook: str | None) -> str | None:
    """Ask the interpreter behind the seen-hook script which seen_core it will import."""
    try:
        first = Path(hook or "").read_text().split("\n", 1)[0]
    except (OSError, UnicodeDecodeError):
        return None
    if not first.startswith("#!"):
        return None
    try:
        out = subprocess.run([first[2:].split()[0], "-I", "-c", "from seen_core import brand;print(brand.VERSION)"],
                             capture_output=True, text=True, timeout=10, cwd=str(paths.home().parent))
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def skew(check_hook: bool = True) -> list[str]:
    """Reasons the installed pieces disagree. A hook older than the ledger schema fails open and records nothing."""
    out = []
    pv = plugin_version()
    if pv and pv != brand.VERSION:
        out.append(f"plugin {pv} installed but the CLI is {brand.VERSION}: run `seen upgrade`")
    rev = ledger_revision()
    if rev:
        try:
            _scripts().get_revision(rev)
        except Exception:
            out.append(f"ledger schema {rev} is newer than this CLI knows (head {schema_head()}): "
                       "upgrade the CLI with `seen upgrade`, or the hook records nothing")
    if check_hook:
        hook = shutil.which("seen-hook")
        hv = hook_version(hook)
        if hv and hv != brand.VERSION:
            out.append(f"seen-hook on PATH is {hv} but `seen` is {brand.VERSION} ({hook}): run `seen upgrade`")
    return out


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "seen-cli", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=3) as r:  # noqa: S310 - fixed https URL
        return str(r.read(1_000_000).decode())


def latest_release(fetch: Callable[[str], str] = _fetch, env: Mapping[str, str] | None = None) -> str | None:
    """Highest vX.Y.Z tag on GitHub, or None offline, on any error, or when SEEN_NO_UPDATE_CHECK is set.
    A plain GET: nothing about this machine is sent."""
    if (os.environ if env is None else env).get("SEEN_NO_UPDATE_CHECK"):
        return None
    try:
        found = [parse_version(t.get("name")) for t in json.loads(fetch(TAGS_URL))]
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    best = max((v for v in found if v), default=None)
    return ".".join(map(str, best)) if best else None


def install_source(receipt: Path | None = None) -> str:
    """Where `uv tool` got seen-cli (a folder or a git URL), so an upgrade reinstalls from the same place."""
    try:
        for r in tomllib.loads((receipt or Path(sys.prefix) / "uv-receipt.toml").read_text())["tool"]["requirements"]:
            if r.get("name") == "seen-cli":
                if r.get("directory"):
                    return str(r["directory"])
                if r.get("git"):
                    return str("git+" + r["git"] + (f"#subdirectory={r['subdirectory']}" if r.get("subdirectory") else ""))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return GITHUB_SPEC


def plan(source: str, have_claude: bool) -> list[list[str]]:
    if source.startswith("-"):
        raise ValueError("source must not start with '-'")
    cmds = [["uv", "tool", "install", "--force", "--reinstall", source]]
    if have_claude:
        cmds += [["claude", "plugin", "marketplace", "update", brand.MARKETPLACE],
                 ["claude", "plugin", "update", f"{brand.PLUGIN}@{brand.MARKETPLACE}"]]
    return cmds


def healthy() -> tuple[bool, str]:
    """Do not replace the tool under a ledger or audit chain that is already in trouble."""
    try:
        from .db import ledger_session

        with ledger_session():
            pass
    except Exception as e:
        return False, f"ledger: {type(e).__name__}"
    v = audit.verify()
    return (True, "") if v.ok else (False, f"audit chain broken at seq {v.break_seq}")


def run(cmds: list[list[str]]) -> list[tuple[list[str], int]]:
    """Run in order, stop at the first failure. argv lists, never a shell."""
    done = []
    for c in cmds:
        try:
            rc = subprocess.run(c).returncode
        except OSError:
            rc = 127
        done.append((c, rc))
        if rc:
            break
    return done
