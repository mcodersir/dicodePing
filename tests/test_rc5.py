from __future__ import annotations

import unittest
from dataclasses import dataclass

from dicodeping.rc5_core import auto_retry_ids, connection_lost_message


@dataclass
class Row:
    id: str


class Rc5Tests(unittest.TestCase):
    def test_auto_retry_plan_is_ranked_unique_and_bounded(self) -> None:
        rows = [Row("a"), Row("a"), Row("b"), Row("c"), Row("d")]
        self.assertEqual(auto_retry_ids(rows, limit=3), ["a", "b", "c"])

    def test_auto_retry_plan_ignores_empty_ids(self) -> None:
        self.assertEqual(auto_retry_ids([Row(""), Row("x")]), ["x"])

    def test_connection_loss_message_names_server(self) -> None:
        self.assertIn("Frankfurt", connection_lost_message("en", "Frankfurt"))
        self.assertIn("Frankfurt", connection_lost_message("fa", "Frankfurt"))


if __name__ == "__main__":
    unittest.main()
