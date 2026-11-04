import json
import socket
import struct
import threading
import unittest

from pose_control import IDLE_VALUES, PARAMETERS, PoseController, joint_angles, osc_float
from pose_receiver import PoseBridge, serve
from test_pose_receiver import packet


def standing():
    frame = packet()
    points = {
        11: (-0.2, 1.0, 0.0), 12: (0.2, 1.0, 0.0),
        13: (-0.5, 0.5, 0.0), 14: (0.5, 0.5, 0.0),
        15: (-0.8, 0.0, 0.0), 16: (0.8, 0.0, 0.0),
        23: (-0.2, 0.0, 0.0), 24: (0.2, 0.0, 0.0),
        25: (-0.2, -0.5, 0.0), 26: (0.2, -0.5, 0.0),
        27: (-0.2, -1.0, 0.0), 28: (0.2, -1.0, 0.0),
    }
    for index, (x, y, z) in points.items():
        frame["worldLandmarks"][index].update(x=x, y=y, z=z)
    return frame


class PoseControlTests(unittest.TestCase):
    def test_six_joint_directions_and_isolation(self):
        neutral = standing()
        neutral_points = {
            13: (-0.6, 1.0, 0.0), 15: (-1.0, 1.0, 0.0),
            14: (0.6, 1.0, 0.0), 16: (1.0, 1.0, 0.0),
        }
        for index, (x, y, z) in neutral_points.items():
            neutral["worldLandmarks"][index].update(x=x, y=y, z=z)
        movements = {
            "Puppet/LeftArmRaise": {13: (-0.2, 1.4, 0.0), 15: (-0.2, 1.8, 0.0)},
            "Puppet/RightArmRaise": {14: (0.2, 1.4, 0.0), 16: (0.2, 1.8, 0.0)},
            "Puppet/LeftElbowFlex": {15: (-0.6, 0.6, 0.0)},
            "Puppet/RightElbowFlex": {16: (0.6, 0.6, 0.0)},
            "Puppet/LeftKneeFlex": {27: (-0.2, -0.5, 0.5)},
            "Puppet/RightKneeFlex": {28: (0.2, -0.5, 0.5)},
        }
        for expected, changes in movements.items():
            with self.subTest(parameter=expected):
                controller = PoseController(calibration_seconds=0.0, smoothing_ms=0,
                                            minimum_calibration_samples=2)
                controller.ingest(neutral, 1_000_000_000)
                controller.ingest(neutral, 1_100_000_000)
                frame = json.loads(json.dumps(neutral))
                for index, (x, y, z) in changes.items():
                    frame["worldLandmarks"][index].update(x=x, y=y, z=z)
                result = controller.ingest(frame, 1_200_000_000)
                for name in PARAMETERS:
                    self.assertAlmostEqual(result[name], 1.0 if name == expected else 0.0, places=6)

        controller = PoseController(calibration_seconds=0.0, smoothing_ms=0,
                                    minimum_calibration_samples=2)
        controller.ingest(neutral, 1_000_000_000)
        controller.ingest(neutral, 1_100_000_000)
        combined = json.loads(json.dumps(neutral))
        combined["worldLandmarks"][13].update(x=-0.2, y=1.4, z=0.0)
        combined["worldLandmarks"][15].update(x=-0.6, y=1.4, z=0.0)
        values = controller.ingest(combined, 1_200_000_000)
        self.assertAlmostEqual(values["Puppet/LeftArmRaise"], 1.0, places=6)
        self.assertAlmostEqual(values["Puppet/LeftElbowFlex"], 1.0, places=6)
        lowered = json.loads(json.dumps(neutral))
        lowered["worldLandmarks"][13].update(x=-0.2, y=0.6, z=0.0)
        lowered["worldLandmarks"][15].update(x=-0.2, y=0.2, z=0.0)
        values = controller.ingest(lowered, 1_300_000_000)
        self.assertAlmostEqual(values["Puppet/LeftArmRaise"], -1.0, places=6)

    def test_geometry_and_missing_confidence(self):
        frame = standing()
        values = joint_angles(frame, 0.5)
        self.assertEqual(set(values), set(PARAMETERS))
        self.assertAlmostEqual(values["Puppet/LeftElbowFlex"], 0.0, places=4)
        frame["landmarks"][15].update(visibility=None, presence=None)
        values = joint_angles(frame, 0.5)
        self.assertNotIn("Puppet/LeftElbowFlex", values)
        self.assertIn("Puppet/RightElbowFlex", values)

    def test_calibration_movement_confidence_and_timeout(self):
        controller = PoseController(calibration_seconds=0.003, smoothing_ms=0, hold_ms=250,
                                    minimum_calibration_samples=2)
        frame = standing()
        self.assertEqual(controller.ingest(frame, 1_000_000_000), {})
        calibrated = controller.ingest(frame, 1_004_000_000)
        self.assertEqual(set(calibrated), set(PARAMETERS))
        self.assertTrue(all(value == 0.0 for value in calibrated.values()))
        frame["worldLandmarks"][15].update(x=-0.2, y=0.5, z=0.0)
        moved = controller.ingest(frame, 1_020_000_000)
        self.assertGreater(moved["Puppet/LeftElbowFlex"], 0.5)
        frame["landmarks"][15]["visibility"] = 0.1
        low = controller.ingest(frame, 1_030_000_000)
        self.assertNotIn("Puppet/LeftElbowFlex", low)
        expired = controller.tick(1_300_000_000)
        self.assertEqual(expired["Puppet/LeftElbowFlex"], 0.0)
        self.assertEqual(expired["Puppet/LeftArmRaise"], -1.0)
        self.assertEqual(expired["Puppet/RightArmRaise"], -1.0)
        self.assertEqual(controller.tick(1_400_000_000), {})
        recovered = controller.ingest(frame, 1_410_000_000)
        self.assertAlmostEqual(recovered["Puppet/LeftArmRaise"], 0.0)

    def test_calibration_does_not_use_stale_joint_samples(self):
        controller = PoseController(calibration_seconds=3.0, smoothing_ms=0,
                                    minimum_calibration_samples=5)
        frame = standing()
        for index in range(5):
            controller.ingest(frame, 1_000_000_000 + index * 100_000_000)
        # The left wrist disappears for longer than the calibration window.
        # Other visible joints must not allow the old elbow samples to pass.
        frame["landmarks"][15]["visibility"] = 0.1
        for index in range(5):
            controller.ingest(frame, 4_200_000_000 + index * 100_000_000)
        self.assertIsNone(controller.baseline)
        frame["landmarks"][15]["visibility"] = 1.0
        for index in range(5):
            controller.ingest(frame, 4_700_000_000 + index * 100_000_000)
        # After the missing joint returns, all joints must remain recently
        # observable for the full calibration duration, not just five frames.
        self.assertIsNone(controller.baseline)
        for index in range(1, 32):
            controller.ingest(frame, 5_100_000_000 + index * 100_000_000)
        self.assertIsNotNone(controller.baseline)

    def test_calibration_restarts_after_all_packets_pause(self):
        controller = PoseController(calibration_seconds=3.0, smoothing_ms=0,
                                    minimum_calibration_samples=5)
        frame = standing()
        for index in range(5):
            controller.ingest(frame, 1_000_000_000 + index * 100_000_000)
        for index in range(5):
            controller.ingest(frame, 5_000_000_000 + index * 100_000_000)
        self.assertIsNone(controller.baseline)

    def test_calibration_tolerates_brief_confidence_dropouts(self):
        controller = PoseController(calibration_seconds=3.0, smoothing_ms=0,
                                    minimum_calibration_samples=5)
        frame = standing()
        for index in range(32):
            frame["landmarks"][15]["visibility"] = 1.0 if index % 2 == 0 else 0.1
            controller.ingest(frame, 1_000_000_000 + index * 100_000_000)
        self.assertIsNotNone(controller.baseline)

    def test_osc_float_wire_format(self):
        raw = osc_float("Puppet/LeftElbowFlex", 0.5)
        self.assertTrue(raw.startswith(b"/avatar/parameters/Puppet/LeftElbowFlex\x00"))
        self.assertEqual(struct.unpack(">f", raw[-4:])[0], 0.5)
        self.assertEqual(len(raw) % 4, 0)
        with self.assertRaises(ValueError):
            osc_float("Other", 0.5)

    def test_udp_pose_to_osc_on_loopback(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as osc, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            osc.bind(("127.0.0.1", 0))
            osc.settimeout(2)
            server.bind(("127.0.0.1", 0))
            bridge = PoseBridge(osc.getsockname()[1], 0.0, 0.0, 250.0)
            bridge.controller.minimum_calibration_samples = 2
            results = []
            worker = threading.Thread(target=lambda: results.append(serve(server, 0.5, 10.0, None, bridge)))
            worker.start()
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                    client.settimeout(2)
                    frame = standing()
                    for seq in (1, 2):
                        frame["seq"] = seq
                        client.sendto(json.dumps(frame).encode(), server.getsockname())
                        ack, _ = client.recvfrom(4096)
                        self.assertEqual(json.loads(ack)["seq"], seq)
                    messages = [osc.recvfrom(4096)[0] for _ in range(2 * len(PARAMETERS))]
                    self.assertEqual(messages[:6], [osc_float(name, IDLE_VALUES[name]) for name in PARAMETERS])
                    self.assertEqual(messages[6:], [osc_float(name, 0.0) for name in PARAMETERS])
            finally:
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
            final = [osc.recvfrom(4096)[0] for _ in PARAMETERS]
            self.assertEqual(final, [osc_float(name, IDLE_VALUES[name]) for name in PARAMETERS])
            self.assertIsNotNone(results[0].summary(0.5)["pose_to_osc_p50_ms"])

    def test_precalibration_idle_is_not_counted_as_pose_to_osc(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as osc, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            osc.bind(("127.0.0.1", 0))
            server.bind(("127.0.0.1", 0))
            bridge = PoseBridge(osc.getsockname()[1], 3.0, 0.0, 250.0)
            results = []
            worker = threading.Thread(target=lambda: results.append(serve(server, 0.4, 10.0, None, bridge)))
            worker.start()
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                    client.settimeout(2)
                    client.sendto(json.dumps(standing()).encode(), server.getsockname())
                    client.recvfrom(4096)
            finally:
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
            self.assertGreater(results[0].osc_updates, 0)
            self.assertIsNone(results[0].summary(0.4)["pose_to_osc_p50_ms"])

    def test_udp_tracking_timeout_recovery_and_new_session(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as osc, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            osc.bind(("127.0.0.1", 0))
            osc.settimeout(2)
            server.bind(("127.0.0.1", 0))
            bridge = PoseBridge(osc.getsockname()[1], 0.0, 0.0, 500.0)
            bridge.controller.minimum_calibration_samples = 2
            worker = threading.Thread(target=serve, args=(server, 3.0, 10.0, None, bridge))
            worker.start()
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                    client.settimeout(2)
                    frame = standing()

                    def send(seq, session="test-session"):
                        frame["seq"] = seq
                        frame["session"] = session
                        client.sendto(json.dumps(frame).encode(), server.getsockname())
                        self.assertEqual(json.loads(client.recvfrom(4096)[0])["seq"], seq)

                    def read_values(expected):
                        received = [osc.recvfrom(4096)[0] for _ in PARAMETERS]
                        self.assertEqual(received, [osc_float(name, expected[name]) for name in PARAMETERS])

                    zeros = dict.fromkeys(PARAMETERS, 0.0)
                    send(1)
                    read_values(IDLE_VALUES)
                    send(2)
                    read_values(zeros)
                    read_values(IDLE_VALUES)  # No packet for the hold period.
                    send(3)
                    read_values(zeros)  # Same session resumes without recalibration.
                    send(1, "new-session")
                    read_values(IDLE_VALUES)  # New session resets and recalibrates.
                    send(2, "new-session")
                    read_values(zeros)
            finally:
                worker.join(timeout=4)
                self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
