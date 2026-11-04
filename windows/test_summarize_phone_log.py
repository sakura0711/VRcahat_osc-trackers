import unittest

from summarize_phone_log import summarize


class PhoneLogTests(unittest.TestCase):
    def test_uses_counts_and_duration_for_weighted_rates(self):
        summary = summarize([
            "POSE_RATE delegate=GPU durationMs=1000.00 results=10 poses=8 resultFps=10.00 poseFps=8.00",
            "POSE_RATE delegate=GPU durationMs=2000.00 results=30 poses=20 resultFps=15.00 poseFps=10.00",
            "POSE_RATE delegate=CPU durationMs=1000.00 results=7 poses=6 resultFps=7.00 poseFps=6.00",
            "UDP sent=80 ack=79 overwritten=2 expired=0 rttP50Ms=12.34 rttP95Ms=23.45 bytes=5200 recentAck=true",
        ])
        gpu = summary["by_delegate"]["GPU"]
        self.assertEqual(gpu["window_seconds"], 3.0)
        self.assertEqual(gpu["result_fps"], 13.33)
        self.assertEqual(gpu["pose_fps"], 9.33)
        self.assertEqual(gpu["windows_below_threshold"], 1)
        self.assertEqual(summary["by_delegate"]["CPU"]["result_fps"], 7.0)
        self.assertEqual(summary["last_udp_status"]["rtt_p95_ms_recent_512"], 23.45)

    def test_invalid_windows_are_excluded(self):
        summary = summarize([
            "POSE_RATE delegate=GPU durationMs=0.00 results=5 poses=3 resultFps=0 poseFps=0",
            "POSE_RATE delegate=GPU durationMs=1000.00 results=1 poses=2 resultFps=1 poseFps=2",
        ])
        self.assertEqual(summary["rejected_rate_windows"], 2)
        self.assertEqual(summary["by_delegate"], {})


if __name__ == "__main__":
    unittest.main()
