import contextlib
import io
import math
import json
import socket
import threading
import time
import unittest
from unittest import mock

from pose_receiver import ReceiverStats, main, serve
from test_pose_receiver import packet
from test_tracker_pose import config, pose
from tracker_bridge import TrackerBridge, TrackerBridgeConfig
from tracker_output import TrackerTransform


SLOTS = {"hip": 1, "left_foot": 3, "right_foot": 4}
TRACKER_ARGS = [
    "--output", "trackers", "--tracker-hip-id", "1", "--tracker-left-foot-id", "3",
    "--tracker-right-foot-id", "4", "--tracker-hip-height", "0.9",
    "--tracker-mirror", "no", "--tracker-swap-left-right", "no",
    "--tracker-forward-sign", "1", "--tracker-yaw", "0",
]


class FakeOutput:
    def __init__(self):
        self.batches = []
        self.closed = False
        self.fail = False

    def send(self, values):
        if self.fail:
            raise OSError("controlled send failure")
        self.batches.append(dict(values))
        return 6

    def close(self):
        self.closed = True


def frame(session="first", **changes):
    value = pose(**changes)
    value["session"] = session
    return value


def ready_bridge(*, loss_ms=250, hold_ms=0, slots=SLOTS):
    output = FakeOutput()
    bridge = TrackerBridge(TrackerBridgeConfig(
        config(loss_timeout_ms=loss_ms), slots, hold_ms=hold_ms), output=output)
    stats = ReceiverStats()
    with contextlib.redirect_stdout(io.StringIO()):
        for moment in (0, 100_000_000, 200_000_000, 300_000_000):
            bridge.on_packet(frame(), moment, stats)
    assert len(output.batches) == 1
    return bridge, output, stats


class TrackerBridgeTests(unittest.TestCase):
    def test_receiver_loopback_sends_only_fresh_calibrated_batch(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, \
             socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender, \
             socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as osc:
            receiver.bind(("127.0.0.1", 0))
            sender.bind(("127.0.0.1", 0))
            osc.bind(("127.0.0.1", 0))
            osc.settimeout(0.1)
            bridge = TrackerBridge(TrackerBridgeConfig(
                config(calibration_seconds=0, minimum_samples=2), SLOTS), port=osc.getsockname()[1])
            results = []
            worker = threading.Thread(target=lambda: results.append(serve(receiver, 0.45, 10, bridge=bridge)))
            with contextlib.redirect_stdout(io.StringIO()):
                worker.start()
                for seq in (1, 2, 3):
                    value = packet(seq=seq)
                    value.update(frame())
                    sender.sendto(json.dumps(value).encode(), receiver.getsockname())
                    time.sleep(0.03)
                low = packet(seq=4)
                low.update(frame())
                low["landmarks"][28]["visibility"] = 0.1
                sender.sendto(json.dumps(low).encode(), receiver.getsockname())
                sender.sendto(json.dumps(low).encode(), receiver.getsockname())  # duplicate
                empty = packet(seq=5, detected=False)
                empty["session"] = "first"
                sender.sendto(json.dumps(empty).encode(), receiver.getsockname())
                worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            messages = []
            while True:
                try:
                    messages.append(osc.recvfrom(1024)[0])
                except socket.timeout:
                    break
            self.assertEqual(len(messages), 6)
            self.assertEqual(results[0].osc_updates, 6)
            self.assertEqual(results[0].out_of_order, 1)
            for role, slot in SLOTS.items():
                self.assertTrue(any(f"/tracking/trackers/{slot}/position".encode() in msg for msg in messages))
                self.assertTrue(any(f"/tracking/trackers/{slot}/rotation".encode() in msg for msg in messages))

    def test_no_output_before_complete_standing_calibration_and_role_mapping(self):
        output = FakeOutput()
        bridge = TrackerBridge(TrackerBridgeConfig(config(), SLOTS), output=output)
        stats = ReceiverStats()
        with contextlib.redirect_stdout(io.StringIO()):
            for moment in (0, 100_000_000, 200_000_000):
                bridge.on_packet(frame(), moment, stats)
            self.assertEqual(output.batches, [])
            bridge.on_packet(frame(), 300_000_000, stats)
        self.assertEqual(set(output.batches[0]), set(SLOTS))
        self.assertEqual(stats.osc_updates, 6)
        self.assertTrue(bridge.output_ready)
        bridge.close(stats)
        self.assertTrue(output.closed)

    def test_low_confidence_no_person_and_missing_point_do_not_refresh(self):
        bridge, output, stats = ready_bridge()
        low = frame()
        low["landmarks"][28]["visibility"] = 0.1
        missing = frame()
        missing["worldLandmarks"][31] = None
        no_person = {"session": "first", "personDetected": False}
        with contextlib.redirect_stdout(io.StringIO()):
            for moment, value in ((350_000_000, low), (400_000_000, no_person),
                                  (450_000_000, missing)):
                bridge.on_packet(value, moment, stats)
                bridge.tick(moment + 1, stats)
            bridge.tick(550_000_001, stats)
            bridge.on_packet(frame(), 600_000_000, stats)
        self.assertEqual(len(output.batches), 1)
        self.assertIsNone(bridge.last_batch)
        self.assertIsNone(bridge.controller.calibration)
        self.assertEqual(bridge.state, "calibrating")

    def test_hold_is_bounded_independently_of_longer_loss_timeout(self):
        bridge, output, stats = ready_bridge(loss_ms=1000, hold_ms=100)
        with contextlib.redirect_stdout(io.StringIO()):
            bridge.on_packet({"session": "first", "personDetected": False}, 340_000_000, stats)
            bridge.tick(350_000_000, stats)
            self.assertEqual(len(output.batches), 2)
            bridge.tick(400_000_001, stats)
            bridge.on_packet({"session": "first", "personDetected": False}, 700_000_000, stats)
            bridge.tick(800_000_000, stats)
            self.assertEqual(len(output.batches), 2)
            bridge.on_packet(frame(right_lift=0.2), 900_000_000, stats)
        self.assertEqual(len(output.batches), 3)
        self.assertAlmostEqual(output.batches[-1]["right_foot"].position[1], 0.28)

    def test_default_and_custom_timeout_force_recalibration(self):
        for timeout in (250, 500):
            with self.subTest(timeout=timeout):
                bridge, output, stats = ready_bridge(loss_ms=timeout)
                with contextlib.redirect_stdout(io.StringIO()):
                    bridge.tick(300_000_000 + timeout * 1_000_000, stats)
                    self.assertEqual(len(output.batches), 1)
                    bridge.tick(300_000_001 + timeout * 1_000_000, stats)
                    self.assertEqual(bridge.state, "lost")
                    bridge.on_packet(frame(), 400_000_001 + timeout * 1_000_000, stats)
                self.assertEqual(len(output.batches), 1)
                self.assertIsNone(bridge.controller.calibration)

    def test_session_change_and_discontinuity_require_recalibration(self):
        bridge, output, stats = ready_bridge()
        with contextlib.redirect_stdout(io.StringIO()):
            bridge.on_packet(frame(session="second"), 350_000_000, stats)
        self.assertEqual(len(output.batches), 1)
        self.assertIsNone(bridge.controller.calibration)
        bridge, output, stats = ready_bridge()
        with contextlib.redirect_stdout(io.StringIO()):
            bridge.on_packet(frame(right_lift=0.7), 350_000_000, stats)
        self.assertEqual(len(output.batches), 1)
        self.assertEqual(bridge.state, "lost")
        self.assertIsNone(bridge.controller.calibration)

    def test_yaw_wrap_uses_shortest_angle_and_output_error_closes(self):
        bridge, output, stats = ready_bridge()
        old = TrackerTransform((0, 0.9, 0), (0, 179, 0))
        new = TrackerTransform((0, 0.9, 0), (0, -179, 0))
        bridge.last_batch = {role: old for role in SLOTS}
        self.assertFalse(bridge._jumped({role: new for role in SLOTS}))
        bridge.last_batch = output.batches[-1]
        output.fail = True
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            bridge.on_packet(frame(), 350_000_000, stats)
        self.assertTrue(output.closed)
        self.assertEqual(stats.osc_errors, 1)
        self.assertIsNone(bridge.controller.calibration)

    def test_invalid_configurations(self):
        for loss, hold in ((0, 0), (5001, 0), (math.inf, 0), (1000, 251), (100, 101), (250, -1)):
            with self.subTest(loss=loss, hold=hold), self.assertRaises(ValueError):
                TrackerBridgeConfig(config(loss_timeout_ms=loss), SLOTS, hold_ms=hold)
        for slots in ({"hip": 1, "left_foot": 3, "right_foot": 3},
                      {"hip": 1, "left_foot": 3},
                      {"hip": 1, "left_foot": 3, "right_foot": 9}):
            with self.assertRaises(ValueError):
                TrackerBridgeConfig(config(), slots)


class TrackerCliTests(unittest.TestCase):
    def test_invalid_output_choices_fail_before_socket_creation(self):
        bad = (
            ["--osc", "--output", "trackers"],
            ["--tracker-loss-ms", "500"],
            ["--output", "trackers"],
            TRACKER_ARGS + ["--tracker-loss-ms", "5001"],
            TRACKER_ARGS + ["--tracker-loss-ms", "1000", "--tracker-hold-ms", "251"],
            TRACKER_ARGS + ["--tracker-right-foot-id", "3"],
        )
        with mock.patch("pose_receiver.socket.socket") as socket_factory:
            for args in bad:
                with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        main(args)
            socket_factory.assert_not_called()

    def test_default_parameters_and_tracker_modes(self):
        class FakeSocket:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def bind(self, *_):
                pass

        captured = []

        def serve_spy(*args):
            captured.append(args[4])

        with mock.patch("pose_receiver.socket.socket", return_value=FakeSocket()), \
             mock.patch("pose_receiver.serve", side_effect=serve_spy), \
             mock.patch("pose_receiver.PoseBridge") as parameters, \
             mock.patch("pose_receiver.TrackerBridge") as trackers, \
             contextlib.redirect_stdout(io.StringIO()):
            main([])
            main(["--osc"])
            main(TRACKER_ARGS)
        self.assertEqual(captured[0], None)
        self.assertIs(captured[1], parameters.return_value)
        self.assertIs(captured[2], trackers.return_value)
        self.assertEqual(trackers.call_args.args[0].calibration.loss_timeout_ms, 250)
        self.assertEqual(trackers.call_args.args[0].hold_ms, 0)


if __name__ == "__main__":
    unittest.main()
