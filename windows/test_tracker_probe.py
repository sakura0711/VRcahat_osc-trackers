import socket
import struct
import subprocess
import sys
import time
import unittest

from tracker_probe import pose, send_pose, vector_message


def decode_message(data):
    # Independent OSC string/float parser: validate padding, tags and length.
    def read_string(offset):
        end = data.index(b"\0", offset)
        next_offset = (end + 4) & ~3
        if any(data[end:next_offset]):
            raise ValueError("nonzero OSC string padding")
        return data[offset:end].decode("ascii"), next_offset

    address, offset = read_string(0)
    tags, offset = read_string(offset)
    if tags != ",fff" or len(data) != offset + 12:
        raise ValueError("unexpected OSC arguments")
    return address, struct.unpack(">fff", data[offset:])


class TrackerProbeTests(unittest.TestCase):
    def test_udp_packets_and_pose_difference(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(1)
            decoded_poses = []
            for raised in (False, True):
                send_pose(sender, receiver.getsockname(), 1.7, raised)
                messages = dict(decode_message(receiver.recvfrom(1024)[0]) for _ in range(6))
                expected = {f"/tracking/trackers/{slot}/{kind}" for slot in (1, 3, 4) for kind in ("position", "rotation")}
                self.assertEqual(set(messages), expected)
                for slot, position in pose(1.7, raised).items():
                    for actual, wanted in zip(messages[f"/tracking/trackers/{slot}/position"], position):
                        self.assertAlmostEqual(actual, wanted, places=6)
                    self.assertEqual(messages[f"/tracking/trackers/{slot}/rotation"], (0.0, 0.0, 0.0))
                decoded_poses.append(messages)
            self.assertGreater(decoded_poses[1]["/tracking/trackers/3/position"][1], decoded_poses[0]["/tracking/trackers/3/position"][1])
            self.assertEqual(decoded_poses[0]["/tracking/trackers/4/position"], decoded_poses[1]["/tracking/trackers/4/position"])

    def test_invalid_values_and_cli(self):
        for slot, kind, values in ((2, "position", (0, 0, 0)), (1, "other", (0, 0, 0)), (1, "rotation", (0, float("nan"), 0))):
            with self.assertRaises(ValueError):
                vector_message(slot, kind, values)
        for arguments in (("--height", "nan"), ("--pose-seconds", "inf"), ("--port", "0"), ("--cycles", "0")):
            result = subprocess.run([sys.executable, "-B", "tracker_probe.py", *arguments], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

    def test_interactive_pose_changes_over_udp(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(2)
            process = subprocess.Popen(
                [sys.executable, "-B", "tracker_probe.py", "--interactive", "--height", "1.7",
                 "--port", str(receiver.getsockname()[1]), "--max-seconds", "10"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                self.assertAlmostEqual(self._left_foot_height(receiver, lambda y: y < 0.1), 0.068, places=3)
                self.assertIsNotNone(process.stdin)
                process.stdin.write("raise\n")
                process.stdin.flush()
                self.assertAlmostEqual(self._left_foot_height(receiver, lambda y: y > 0.3), 0.408, places=3)
                process.stdin.write("stand\n")
                process.stdin.flush()
                self.assertAlmostEqual(self._left_foot_height(receiver, lambda y: y < 0.1), 0.068, places=3)
                process.stdin.write("quit\n")
                process.stdin.flush()
                stdout, stderr = process.communicate(timeout=3)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertIn("tracker 3 raised", stdout)
                self.assertIn("Stopped sending", stdout)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    @staticmethod
    def _left_foot_height(receiver, predicate):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            address, values = decode_message(receiver.recvfrom(1024)[0])
            if address == "/tracking/trackers/3/position" and predicate(values[1]):
                return values[1]
        raise AssertionError("left foot pose did not change")


if __name__ == "__main__":
    unittest.main()
