from __future__ import annotations

import unittest
from types import SimpleNamespace

from dicodeping.rc8_core import (
    geo_lookup_ips,
    is_current_worker,
    primary_action_key,
    responsive_server_columns,
    unresolved_retry_hosts,
)


class Rc8Tests(unittest.TestCase):
    def test_primary_action_does_not_offer_connect_without_servers(self) -> None:
        key = primary_action_key(
            connected=False, busy=False, has_servers=False,
            manual=False, has_selected=False, has_best=False,
        )
        self.assertEqual(key, "update_servers")

    def test_primary_action_distinguishes_manual_selection_and_refresh(self) -> None:
        manual = primary_action_key(
            connected=False, busy=False, has_servers=True,
            manual=True, has_selected=False, has_best=True,
        )
        automatic = primary_action_key(
            connected=False, busy=False, has_servers=True,
            manual=False, has_selected=False, has_best=False,
        )
        self.assertEqual(manual, "select_server")
        self.assertEqual(automatic, "refresh_ping")

    def test_responsive_columns_use_actual_viewport_thresholds(self) -> None:
        self.assertEqual(responsive_server_columns(500), {2: False, 3: False, 5: False})
        self.assertEqual(responsive_server_columns(750), {2: True, 3: False, 5: True})
        self.assertEqual(responsive_server_columns(950), {2: True, 3: True, 5: True})

    def test_geo_skips_unresponsive_servers_and_deduplicates(self) -> None:
        rows = [
            SimpleNamespace(ip="1.1.1.1", status="online", ping_ms=25),
            SimpleNamespace(ip="1.1.1.1", status="online", ping_ms=30),
            SimpleNamespace(ip="2.2.2.2", status="unverified", ping_ms=None),
        ]
        self.assertEqual(geo_lookup_ips(rows), ["1.1.1.1"])

    def test_dns_failures_are_resolved_again_before_retry(self) -> None:
        failed = [("a.example", 443), ("b.example", 80), ("a.example", 8443)]
        resolved = {failed[0]: [], failed[1]: ["192.0.2.1"], failed[2]: []}
        self.assertEqual(unresolved_retry_hosts(failed, resolved), ["a.example"])

    def test_stale_worker_completion_cannot_clear_new_worker(self) -> None:
        old, current = object(), object()
        self.assertFalse(is_current_worker(current, old))
        self.assertTrue(is_current_worker(current, current))


if __name__ == "__main__":
    unittest.main()
