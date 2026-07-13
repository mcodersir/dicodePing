from __future__ import annotations

import unittest

from dicodeping.rc3_core import display_latency, median_latency, trusted_latency


class Rc3LatencyTests(unittest.TestCase):
    def test_uses_median_instead_of_fast_outlier(self):
        self.assertEqual(median_latency([7, 104, 111]), 104)

    def test_auto_latency_threshold_remains_trusted(self):
        self.assertFalse(trusted_latency(7, 70))
        self.assertTrue(trusted_latency(70, 70))

    def test_untrusted_display_is_hidden(self):
        self.assertEqual(display_latency(7), "—")
        self.assertEqual(display_latency(95), "95 ms")


if __name__ == "__main__":
    unittest.main()
