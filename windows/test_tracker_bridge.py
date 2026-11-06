import contextlib
import io
import math
import json
import socket
import threading
import time
import unittest
from unittest import mock

from pose_receiver import ReceiverStats, main, serve, poll_recalibration_key
from test_pose_receiver import packet
from test_tracker_pose import config, pose
from tracker_bridge import TrackerBridge, TrackerBridgeConfig
from tracker_output import TrackerTransform
from console_status import StatusConsole


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


def ready_bridge(*, loss_ms=350, hold_ms=8000, slots=SLOTS):
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
    def test_calibration_status_gives_lower_bound_and_blocking_landmarks(self):
        bridge = TrackerBridge(TrackerBridgeConfig(config(calibration_seconds=3), SLOTS),
                               output=FakeOutput(), console=StatusConsole("never"))
        stats = ReceiverStats()
        with contextlib.redirect_stdout(io.StringIO()):
            for moment in (0, 100_000_000, 200_000_000):
                bridge.on_packet(frame(), moment, stats)
        label, message = bridge.status_line(200_000_000)
        self.assertEqual(label, "loading")
        self.assertIn("earliest 2.8s", message)
        self.assertIn("OSC blocked", message)
        low = frame()
        low["landmarks"][28]["visibility"] = 0.1
        bridge.on_packet(low, 250_000_000, stats)
        label, message = bridge.status_line(250_000_000)
        self.assertEqual(label, "check")
        self.assertIn("right_ankle", message)
        self.assertNotIn("earliest", message)
        self.assertEqual(stats.osc_updates, 0)

    def test_calibration_progress_is_throttled_to_one_line_per_second(self):
        bridge = TrackerBridge(TrackerBridgeConfig(config(calibration_seconds=3), SLOTS),
                               output=FakeOutput(), console=StatusConsole("never"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for moment in (0, 200_000_000, 400_000_000, 600_000_000, 800_000_000,
                           1_000_000_000, 1_200_000_000):
                bridge.on_packet(frame(), moment, ReceiverStats())
        progress = [line for line in output.getvalue().splitlines() if "earliest" in line]
        self.assertEqual(len(progress), 2)
        self.assertIn("earliest 3.0s", progress[0])
        self.assertIn("earliest 2.0s", progress[1])

    def test_short_pause_resume_does_not_spam_transition_lines(self):
        bridge, _, stats = ready_bridge(loss_ms=1000)
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            for moment in (450_000_000, 600_000_000, 750_000_000):
                bridge.tick(moment, stats)
                bridge.on_packet(frame(), moment + 1, stats)
        self.assertEqual(captured.getvalue(), "")
        self.assertEqual(bridge.status_line(750_000_001)[0], "ready")

    def test_receiver_loopback_sends_only_fresh_calibrated_batch(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, \
             socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender, \
             socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as osc:
            receiver.bind(("127.0.0.1", 0))
            sender.bind(("127.0.0.1", 0))
            osc.bind(("127.0.0.1", 0))
            osc.settimeout(0.1)
            bridge = TrackerBridge(TrackerBridgeConfig(
                config(calibration_seconds=0, minimum_samples=2), SLOTS, hold_ms=0), port=osc.getsockname()[1])
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
            bridge.tick(650_000_001, stats)
        self.assertTrue(all(batch == output.batches[0] for batch in output.batches))
        self.assertEqual(bridge.last_valid_ns, 300_000_000)
        self.assertIsNotNone(bridge.controller.calibration)
        self.assertEqual(bridge.state, "frozen")

    def test_freeze_expires_without_refresh_and_requires_manual_recalibration(self):
        bridge, output, stats = ready_bridge()
        with contextlib.redirect_stdout(io.StringIO()):
            bridge.on_packet({"session": "first", "personDetected": False}, 340_000_000, stats)
            bridge.tick(8_300_000_000, stats)
            count = len(output.batches)
            self.assertEqual(output.batches[-1], output.batches[0])
            bridge.tick(8_300_000_001, stats)
            bridge.on_packet(frame(), 8_400_000_000, stats)
            self.assertEqual(len(output.batches), count)
            self.assertTrue(bridge.expired)
            self.assertIsNotNone(bridge.controller.calibration)
            bridge.recalibrate()
            self.assertIsNone(bridge.controller.calibration)
            self.assertFalse(bridge.expired)
            bridge.on_packet(frame(), 8_500_000_000, stats)
            self.assertEqual(len(output.batches), count)

    def test_loss_keeps_calibration_and_recovery_interpolates_current_target(self):
        bridge, output, stats = ready_bridge()
        with contextlib.redirect_stdout(io.StringIO()):
            bridge.tick(650_000_001, stats)
            self.assertEqual(bridge.state, "frozen")
            bridge.on_packet(frame(right_lift=0.2), 700_000_000, stats)
            self.assertAlmostEqual(output.batches[-1]["right_foot"].position[1], 0.08)
            bridge.on_packet(frame(right_lift=0.3), 850_000_000, stats)
            self.assertAlmostEqual(output.batches[-1]["right_foot"].position[1], 0.23)
            bridge.on_packet(frame(right_lift=0.3), 1_000_000_000, stats)
            self.assertAlmostEqual(output.batches[-1]["right_foot"].position[1], 0.38)
        self.assertIsNotNone(bridge.controller.calibration)

    def test_resume_yaw_uses_shortest_path_and_new_session_discards_freeze(self):
        bridge, output, stats = ready_bridge()
        old = TrackerTransform((0, 0.9, 0), (0, 179, 0))
        new = TrackerTransform((0, 0.9, 0), (0, -179, 0))
        bridge.last_batch = {role: old for role in SLOTS}
        bridge.last_sent = dict(bridge.last_batch)
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(
                bridge.controller, "ingest", return_value={role: new for role in SLOTS}):
            bridge.on_packet(frame(), 700_000_000, stats)
            bridge.on_packet(frame(), 850_000_000, stats)
            self.assertAlmostEqual(output.batches[-1]["hip"].rotation[1], 180)
            bridge.on_packet(frame(), 1_000_000_000, stats)
            self.assertAlmostEqual(output.batches[-1]["hip"].rotation[1] % 360, 181)
        with contextlib.redirect_stdout(io.StringIO()):
            bridge.on_packet(frame(session="second"), 1_100_000_000, stats)
        self.assertIsNone(bridge.last_sent)
        self.assertIsNone(bridge.controller.calibration)

    def test_invalid_frame_during_transition_freezes_last_sent_and_restarts_smoothly(self):
        bridge, output, stats = ready_bridge()
        with contextlib.redirect_stdout(io.StringIO()):
            bridge.tick(700_000_000, stats)
            bridge.on_packet(frame(right_lift=0.2), 710_000_000, stats)
            bridge.on_packet(frame(right_lift=0.2), 810_000_000, stats)
            last_sent = output.batches[-1]
            bridge.on_packet({"session": "first", "personDetected": False}, 820_000_000, stats)
            bridge.tick(870_000_000, stats)
            self.assertEqual(output.batches[-1], last_sent)
            bridge.on_packet(frame(right_lift=0.3), 880_000_000, stats)
            self.assertEqual(output.batches[-1], last_sent)

    def test_resume_jump_never_blends_invalid_target(self):
        bridge, output, stats = ready_bridge()
        with contextlib.redirect_stdout(io.StringIO()):
            bridge.tick(700_000_000, stats)
            count = len(output.batches)
            bridge.on_packet(frame(right_lift=0.7), 710_000_000, stats)
        self.assertEqual(len(output.batches), count)
        self.assertIsNone(bridge.controller.calibration)
        self.assertIsNone(bridge.last_sent)

    def test_recovery_output_cannot_jump_when_target_moves_during_blend(self):
        bridge, output, stats = ready_bridge()
        with contextlib.redirect_stdout(io.StringIO()):
            bridge.tick(700_000_000, stats)
            bridge.on_packet(frame(right_lift=0.4), 710_000_000, stats)
            count = len(output.batches)
            bridge.on_packet(frame(right_lift=0.8), 1_010_000_000, stats)
        self.assertEqual(len(output.batches), count)
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
        for loss, hold in ((0, 0), (5001, 0), (math.inf, 0), (1000, 251), (350, -1), (350, 8001)):
            with self.subTest(loss=loss, hold=hold), self.assertRaises(ValueError):
                TrackerBridgeConfig(config(loss_timeout_ms=loss), SLOTS, hold_ms=hold)
        for slots in ({"hip": 1, "left_foot": 3, "right_foot": 3},
                      {"hip": 1, "left_foot": 3},
                      {"hip": 1, "left_foot": 3, "right_foot": 9}):
            with self.assertRaises(ValueError):
                TrackerBridgeConfig(config(), slots)


class TrackerCliTests(unittest.TestCase):
    def test_windows_recalibration_key_is_nonblocking_and_explicit(self):
        fake_bridge = mock.Mock()
        keys = iter(("x", "R"))
        with mock.patch("pose_receiver.sys.platform", "win32"), \
             mock.patch("pose_receiver.sys.stdin") as stdin, \
             mock.patch("msvcrt.kbhit", side_effect=(True, True, False)), \
             mock.patch("msvcrt.getwch", side_effect=lambda: next(keys)):
            stdin.isatty.return_value = True
            poll_recalibration_key(fake_bridge)
        fake_bridge.recalibrate.assert_called_once_with()

    def test_invalid_output_choices_fail_before_socket_creation(self):
        bad = (
            ["--osc"],
            ["--output", "parameters"],
            ["--smoothing-ms", "35"],
            ["--hold-ms", "250"],
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

    def test_default_and_tracker_modes(self):
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
             mock.patch("pose_receiver.TrackerBridge") as trackers, \
             contextlib.redirect_stdout(io.StringIO()):
            main([])
            main(TRACKER_ARGS)
        self.assertEqual(captured[0], None)
        self.assertIs(captured[1], trackers.return_value)
        self.assertEqual(trackers.call_args.args[0].calibration.loss_timeout_ms, 350)
        self.assertEqual(trackers.call_args.args[0].hold_ms, 8000)


if __name__ == "__main__":
    unittest.main()
