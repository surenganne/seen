import json
import sqlite3
import sys
from pathlib import Path

from seen_core import brand, paths, upgrade
from seen_core.db import ledger_engine


def test_parse_version() -> None:
    assert upgrade.parse_version("v0.2.10") == (0, 2, 10) and upgrade.parse_version("1.0.0") == (1, 0, 0)
    assert upgrade.parse_version("0.2.0rc1") is None and upgrade.parse_version("main") is None


def write_plugins(tmp_path: Path, version: str | None) -> None:
    d = tmp_path / "claude-config" / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    rows = {"plugins": {f"{brand.PLUGIN}@{brand.MARKETPLACE}": [{"version": version}]}} if version else {"plugins": {}}
    (d / "installed_plugins.json").write_text(json.dumps(rows))


def test_plugin_installed_version(tmp_path: Path) -> None:
    assert upgrade.plugin_version() is None
    write_plugins(tmp_path, "0.1.0")
    assert upgrade.plugin_version() == "0.1.0"


def test_skew_is_empty_when_everything_matches(tmp_path: Path) -> None:
    write_plugins(tmp_path, brand.VERSION)
    ledger_engine()
    assert upgrade.skew(check_hook=False) == []


def test_skew_flags_plugin_version_mismatch(tmp_path: Path) -> None:
    write_plugins(tmp_path, "0.0.1")
    assert any("plugin" in s and "0.0.1" in s for s in upgrade.skew(check_hook=False))


def test_skew_flags_a_ledger_newer_than_this_cli(tmp_path: Path) -> None:
    write_plugins(tmp_path, brand.VERSION)
    ledger_engine()
    c = sqlite3.connect(paths.ledger_db())
    c.execute("update alembic_version set version_num='9999_from_the_future'")
    c.commit()
    c.close()
    msgs = upgrade.skew(check_hook=False)
    assert any("newer" in s and "upgrade" in s.lower() for s in msgs)
    assert upgrade.schema_head() != "9999_from_the_future"


def test_latest_release_picks_highest_release_tag() -> None:
    tags = json.dumps([{"name": "v0.1.0"}, {"name": "v0.10.0"}, {"name": "v0.9.3"}, {"name": "nightly"}])
    assert upgrade.latest_release(fetch=lambda _u: tags, env={}) == "0.10.0"


def test_latest_release_is_quiet_on_failure_and_respects_opt_out() -> None:
    def boom(_u: str) -> str:
        raise OSError("offline")

    assert upgrade.latest_release(fetch=boom, env={}) is None
    assert upgrade.latest_release(fetch=lambda _u: "not json", env={}) is None
    called: list[str] = []
    assert upgrade.latest_release(fetch=lambda u: called.append(u) or "[]", env={"SEEN_NO_UPDATE_CHECK": "1"}) is None
    assert called == []


def test_is_newer() -> None:
    assert upgrade.is_newer("0.2.0", "0.1.9") and not upgrade.is_newer("0.1.0", "0.1.0") and not upgrade.is_newer(None, "0.1.0")


def receipt(tmp_path: Path, req: str) -> Path:
    p = tmp_path / "uv-receipt.toml"
    p.write_text(f"[tool]\nrequirements = [{req}]\n")
    return p


def test_install_source_reuses_where_the_tool_came_from(tmp_path: Path) -> None:
    assert upgrade.install_source(receipt(tmp_path, '{ name = "seen-cli", directory = "/work/seen/packages/cli" }')) == "/work/seen/packages/cli"
    got = upgrade.install_source(receipt(tmp_path, '{ name = "seen-cli", git = "https://github.com/x/seen", subdirectory = "packages/cli" }'))
    assert got == "git+https://github.com/x/seen#subdirectory=packages/cli"
    assert upgrade.install_source(tmp_path / "missing.toml") == upgrade.GITHUB_SPEC


def test_plan_commands() -> None:
    full = upgrade.plan("/src", have_claude=True)
    assert full[0] == ["uv", "tool", "install", "--force", "--reinstall", "/src"]
    assert ["claude", "plugin", "marketplace", "update", brand.MARKETPLACE] in full
    assert ["claude", "plugin", "update", f"{brand.PLUGIN}@{brand.MARKETPLACE}"] in full
    assert upgrade.plan("/src", have_claude=False) == [full[0]]


def test_hook_version_reads_the_binary_that_will_run(tmp_path: Path) -> None:
    hook = tmp_path / "seen-hook"
    hook.write_text(f"#!{sys.executable}\nprint('x')\n")
    hook.chmod(0o755)
    assert upgrade.hook_version(str(hook)) == brand.VERSION
    assert upgrade.hook_version(str(tmp_path / "nope")) is None


def test_run_stops_at_the_first_failure() -> None:
    res = upgrade.run([[sys.executable, "-c", "pass"], [sys.executable, "-c", "raise SystemExit(3)"], [sys.executable, "-c", "pass"]])
    assert [rc for _c, rc in res] == [0, 3]
