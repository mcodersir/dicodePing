import unittest

from dicodeping.rc4_core import preferred_display_name, usable_for_auto
from dicodeping.models import ServerRecord
from dicodeping.service import _is_auto_candidate, is_restricted_location


class Rc4Tests(unittest.TestCase):
    def test_auto_selection_does_not_depend_on_geo(self) -> None:
        self.assertTrue(usable_for_auto("online", 1))
        self.assertFalse(usable_for_auto("unverified", 95))
        self.assertFalse(usable_for_auto("online", None))

    def test_explicit_config_name_is_preserved(self) -> None:
        self.assertEqual(preferred_display_name("🇩🇪 Frankfurt 01", "VLESS • host:443"), "🇩🇪 Frankfurt 01")
        self.assertEqual(preferred_display_name("", "VLESS • host:443"), "VLESS • host:443")

    def test_automatic_connection_requires_70ms_and_non_iran_location(self) -> None:
        row = ServerRecord("one", "One", "VLESS", "host", 443, "blob", ping_ms=69, ip="1.1.1.1", country="Germany", country_code="DE", status="online")
        self.assertFalse(_is_auto_candidate(row))
        row.ping_ms = 70
        self.assertTrue(_is_auto_candidate(row))
        row.country_code = "IR"
        self.assertTrue(is_restricted_location(row))
        self.assertFalse(_is_auto_candidate(row))


if __name__ == "__main__":
    unittest.main()
