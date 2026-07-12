import unittest
from unittest.mock import patch

from shared.connection_quality import ProbeResult, choose_best, tcp_connect_probe


class ConnectionQualityTests(unittest.TestCase):
    def test_choose_best_ignores_failed_results(self):
        selected = choose_best([
            ('broken', ProbeResult(False, None, 'proxy-http', 'failed')),
            ('slow', ProbeResult(True, 180.0, 'proxy-http', samples_ms=(170.0, 190.0))),
            ('fast', ProbeResult(True, 80.0, 'proxy-http', samples_ms=(78.0, 82.0))),
        ])
        self.assertEqual(selected, 'fast')

    def test_jitter_penalty_breaks_close_scores(self):
        selected = choose_best([
            ('unstable', ProbeResult(True, 70.0, 'proxy-http', samples_ms=(20.0, 70.0, 120.0))),
            ('stable', ProbeResult(True, 78.0, 'proxy-http', samples_ms=(77.0, 78.0, 79.0))),
        ])
        self.assertEqual(selected, 'stable')

    def test_invalid_tcp_target_fails_without_socket(self):
        with patch('socket.create_connection') as create:
            result = tcp_connect_probe('', 0)
        self.assertFalse(result.ok)
        create.assert_not_called()


if __name__ == '__main__':
    unittest.main()
