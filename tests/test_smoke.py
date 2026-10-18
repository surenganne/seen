def test_packages_import() -> None:
    import seen_cli
    import seen_core
    import seen_local
    import seen_team

    assert all(m.__name__ for m in (seen_core, seen_cli, seen_local, seen_team))
