from __future__ import annotations

import unittest

from dicodeping.rc3_core import display_latency, median_latency, trusted_latency


class Rc3LatencyTests(unittest.TestCase):
    def test_uses_median_instead_of_fast_outlier(self):
        self.assertEqual(median_latency([7, 104, 111]), 104)

    def test_valid_low_latency_is_displayed(self):
        self.assertTrue(trusted_latency(7))
        self.assertTrue(trusted_latency(70, 70))

    def test_valid_display_is_not_hidden(self):
        self.assertEqual(display_latency(7), "7 ms")
        self.assertEqual(display_latency(95), "95 ms")


if __name__ == "__main__":
    unittest.main()
