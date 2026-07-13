from dicodeping.rc4_core import preferred_display_name, usable_for_auto


def test_auto_selection_does_not_depend_on_geo() -> None:
    assert usable_for_auto("online", 1)
    assert not usable_for_auto("unverified", 95)
    assert not usable_for_auto("online", None)


def test_explicit_config_name_is_preserved() -> None:
    assert preferred_display_name("🇩🇪 Frankfurt 01", "VLESS • host:443") == "🇩🇪 Frankfurt 01"
    assert preferred_display_name("", "VLESS • host:443") == "VLESS • host:443"
