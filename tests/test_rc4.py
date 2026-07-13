import unittest

from dicodeping.rc4_core import preferred_display_name, usable_for_auto


class Rc4Tests(unittest.TestCase):
    def test_auto_selection_does_not_depend_on_geo(self) -> None:
        self.assertTrue(usable_for_auto("online", 1))
        self.assertFalse(usable_for_auto("unverified", 95))
        self.assertFalse(usable_for_auto("online", None))

    def test_explicit_config_name_is_preserved(self) -> None:
        self.assertEqual(preferred_display_name("🇩🇪 Frankfurt 01", "VLESS • host:443"), "🇩🇪 Frankfurt 01")
        self.assertEqual(preferred_display_name("", "VLESS • host:443"), "VLESS • host:443")


if __name__ == "__main__":
    unittest.main()
