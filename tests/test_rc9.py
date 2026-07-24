from __future__ import annotations

import unittest

from dicodeping.rc9_core import StartupGate, server_refresh_due, startup_rows


class Rc9StartupTests(unittest.TestCase):
    def test_startup_gate_allows_only_one_completion_path(self) -> None:
        gate = StartupGate()
        self.assertTrue(gate.claim())
        self.assertFalse(gate.claim())

    def test_empty_or_invalid_cache_is_always_due(self) -> None:
        self.assertTrue(server_refresh_due(0, 100, now=101, interval_seconds=1000))
        self.assertTrue(server_refresh_due(5, "invalid", now=101, interval_seconds=1000))

    def test_fresh_cache_does_not_refresh_during_startup(self) -> None:
        self.assertFalse(server_refresh_due(5, 100, now=150, interval_seconds=100))
        self.assertTrue(server_refresh_due(5, 100, now=201, interval_seconds=100))

    def test_startup_rows_is_bounded_and_type_safe(self) -> None:
        rows = list(range(500))
        self.assertEqual(startup_rows(rows), rows[:320])
        self.assertEqual(startup_rows("not-a-list"), [])
        self.assertEqual(startup_rows(rows, limit=-1), [])


if __name__ == "__main__":
    unittest.main()
