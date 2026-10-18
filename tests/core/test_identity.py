from pathlib import Path

from seen_core import identity, paths


def test_user_id_is_keyed_not_plain_hash(seen_home: Path) -> None:
    a = identity.user_id()
    assert a.startswith("u_") and paths.secret_key().exists()
    assert (paths.secret_key().stat().st_mode & 0o777) == 0o600
    paths.secret_key().write_bytes(b"k" * 32)
    assert identity.user_id() != a  # depends on the per-install key


def test_configured_email_never_stored_raw(seen_home: Path) -> None:
    paths.ensure_dir(seen_home)
    paths.config_toml().write_text('[user]\nid = "dev.person@corp.test"\n')
    uid = identity.user_id()
    assert "@" not in uid and "dev.person" not in uid
    paths.config_toml().write_text('[user]\nid = "team-alpha-7"\n')
    assert identity.user_id() == "team-alpha-7"
