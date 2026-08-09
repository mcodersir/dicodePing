from dicodeping.design_system import WindowClass, desktop_server_columns, window_class


def test_window_class_boundaries():
    assert window_class(899) is WindowClass.COMPACT
    assert window_class(900) is WindowClass.MEDIUM
    assert window_class(1179) is WindowClass.MEDIUM
    assert window_class(1180) is WindowClass.EXPANDED


def test_compact_uses_cards_instead_of_partial_table():
    assert not any(desktop_server_columns(680).values())


def test_medium_keeps_ping_pin_and_action():
    columns = desktop_server_columns(1000)
    assert columns[4] and columns[6] and columns[7]
    assert not columns[2] and not columns[3]


def test_expanded_has_all_server_columns():
    assert all(desktop_server_columns(1440).values())
