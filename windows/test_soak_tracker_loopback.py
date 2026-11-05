import contextlib
import io
import threading
import time
import unittest
from unittest import mock

from soak_tracker_loopback import run


class TrackerSoakStopTests(unittest.TestCase):
    def test_early_interrupt_closes_receiver_without_waiting_full_run(self):
        started = time.monotonic()
        with contextlib.redirect_stdout(io.StringIO()):
            with mock.patch("soak_tracker_loopback.synthetic_packet", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    run(cycles=20, fps=20)
        self.assertLess(time.monotonic() - started, 4.0)
        self.assertFalse(any(worker.name == "tracker-soak-receiver" for worker in threading.enumerate()))


if __name__ == "__main__":
    unittest.main()
