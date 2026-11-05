import socket
import unittest

from test_tracker_probe import decode_message
from tracker_output import TrackerOutput, TrackerTransform, osc_vector


class TrackerOutputTests(unittest.TestCase):
    def test_explicit_role_mapping_and_udp_payload(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(1)
            output = TrackerOutput(
                {"hip": 1, "left_foot": 4, "right_foot": 3},
                port=receiver.getsockname()[1],
            )
            try:
                count = output.send({
                    "hip": TrackerTransform((0.0, 0.9, 0.0), (0.0, 90.0, 0.0)),
                    "left_foot": TrackerTransform((-0.1, 0.05, 0.0), (1.0, 2.0, 3.0)),
                    "right_foot": TrackerTransform((0.1, 0.4, 0.0), (4.0, 5.0, 6.0)),
                })
                self.assertEqual(count, 6)
                packets = dict(decode_message(receiver.recvfrom(1024)[0]) for _ in range(count))
                self.assertEqual(packets, {
                    "/tracking/trackers/1/position": (0.0, 0.8999999761581421, 0.0),
                    "/tracking/trackers/1/rotation": (0.0, 90.0, 0.0),
                    "/tracking/trackers/4/position": (-0.10000000149011612, 0.05000000074505806, 0.0),
                    "/tracking/trackers/4/rotation": (1.0, 2.0, 3.0),
                    "/tracking/trackers/3/position": (0.10000000149011612, 0.4000000059604645, 0.0),
                    "/tracking/trackers/3/rotation": (4.0, 5.0, 6.0),
                })
            finally:
                output.close()

    def test_invalid_batch_sends_nothing(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(0.1)
            output = TrackerOutput(
                {"hip": 1, "left_foot": 3, "right_foot": 4},
                port=receiver.getsockname()[1],
            )
            try:
                with self.assertRaises(ValueError):
                    output.send({
                        "hip": TrackerTransform((0.0, 0.9, 0.0), (0.0, 0.0, 0.0)),
                        "right_foot": TrackerTransform((0.0, float("nan"), 0.0), (0.0, 0.0, 0.0)),
                    })
                with self.assertRaises(socket.timeout):
                    receiver.recvfrom(1024)
            finally:
                output.close()

    def test_mapping_and_vector_validation(self):
        for mapping in (
            {"hip": 1, "left_foot": 3},
            {"hip": 1, "left_foot": 3, "right_foot": 3},
            {"hip": 1, "left_foot": 3, "right_foot": 9},
        ):
            with self.assertRaises(ValueError):
                TrackerOutput(mapping)
        for slot, kind, values in (
            (0, "position", (0, 0, 0)),
            (True, "position", (0, 0, 0)),
            (1, "unknown", (0, 0, 0)),
            (1, "position", (0, 0)),
            (1, "position", (0, float("inf"), 0)),
            (1, "rotation", (0, 1e100, 0)),
        ):
            with self.assertRaises(ValueError):
                osc_vector(slot, kind, values)


if __name__ == "__main__":
    unittest.main()
