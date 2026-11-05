import contextlib
import io
import json
import socket
import threading
import unittest
from unittest import mock

from pose_receiver import serve
from test_pose_receiver import encode, packet
from test_tracker_pose import config, pose
from tracker_preview import TrackerPreview, main


class TrackerPreviewTests(unittest.TestCase):
    def test_calibration_preview_and_loss_without_osc(self):
        preview = TrackerPreview(config(), display_interval_s=0)
        frame = pose()
        frame["session"] = "phone-session"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for moment in (0, 100_000_000, 200_000_000, 300_000_000):
                preview.on_packet(frame, moment)
            preview.tick(600_000_001)
        lines = output.getvalue().splitlines()
        self.assertEqual(sum(line.startswith("PREVIEW_CALIBRATED ") for line in lines), 1)
        values = [json.loads(line.removeprefix("PREVIEW_TRACKERS "))
                  for line in lines if line.startswith("PREVIEW_TRACKERS ")]
        self.assertEqual(len(values), 1)
        self.assertEqual(set(values[0]), {"hip", "left_foot", "right_foot"})
        self.assertEqual(values[0]["hip"]["position_m"], [0.0, 0.9, 0.0])
        self.assertTrue(any(line.startswith("PREVIEW_LOST:") for line in lines))

    def test_new_session_requires_new_calibration(self):
        preview = TrackerPreview(config(), display_interval_s=0)
        frame = pose()
        frame["session"] = "first"
        with contextlib.redirect_stdout(io.StringIO()):
            for moment in (0, 100_000_000, 200_000_000):
                preview.on_packet(frame, moment)
            self.assertIsNotNone(preview.controller.calibration)
            frame["session"] = "second"
            preview.on_packet(frame, 300_000_000)
        self.assertIsNone(preview.controller.calibration)
        self.assertEqual(len(preview.controller.samples), 1)

    def test_quality_totals_survive_display_throttling_loss_and_new_session(self):
        preview = TrackerPreview(config(), display_interval_s=100, summary_only=True)
        frame = pose()
        frame["session"] = "first"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for moment in (0, 100_000_000, 200_000_000, 300_000_000):
                preview.on_packet(frame, moment)
            bad = pose()
            bad["session"] = "first"
            for index in (27, 31):
                bad["landmarks"][index]["visibility"] = 0.1
            preview.on_packet(bad, 400_000_000)
            preview.tick(600_000_001)
            preview.tick(650_000_000)
            preview.on_packet({"session": "first", "personDetected": False}, 700_000_000)
            frame["session"] = "second"
            preview.on_packet(frame, 800_000_000)
            preview.tick(5_800_000_000)
            preview.report_final()
        expected = {
            "accepted_frames": 7, "pose_frames": 6, "transform_frames": 1,
            "transform_frame_pct": 14.29, "sessions": 2,
            "calibrations": 1, "tracking_losses": 1,
            "rejection_frames": {"image_confidence": 1, "no_person": 1},
            "blocked_landmark_frames": {"left_ankle": 1, "left_toe": 1},
        }
        self.assertEqual(preview.summary(), expected)
        lines = output.getvalue().splitlines()
        final = next(line for line in lines if line.startswith("PREVIEW_FINAL "))
        self.assertEqual(json.loads(final.removeprefix("PREVIEW_FINAL ")), expected)
        self.assertTrue(any(line.startswith("PREVIEW_QUALITY ") for line in lines))
        self.assertNotIn("position_m", output.getvalue())

    def test_packet_after_timeout_counts_one_loss(self):
        preview = TrackerPreview(config(), summary_only=True)
        frame = pose()
        frame["session"] = "first"
        with contextlib.redirect_stdout(io.StringIO()):
            for moment in (0, 100_000_000, 200_000_000, 300_000_000, 600_000_001):
                preview.on_packet(frame, moment)
            preview.tick(620_000_000)
        self.assertEqual(preview.summary()["tracking_losses"], 1)
        self.assertIsNone(preview.controller.calibration)

    def test_receiver_observer_sees_only_accepted_packets(self):
        class Observer:
            def __init__(self):
                self.sequences = []
                self.ticks = 0

            def on_packet(self, value, now_ns):
                self.sequences.append(value["seq"])

            def tick(self, now_ns):
                self.ticks += 1

        observer = Observer()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(("127.0.0.1", 0))
            worker = threading.Thread(target=serve,
                                      args=(server, 0.4, 10.0),
                                      kwargs={"observer": observer})
            with contextlib.redirect_stdout(io.StringIO()):
                worker.start()
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                        client.settimeout(1)
                        client.sendto(encode(packet(seq=1)), server.getsockname())
                        self.assertEqual(json.loads(client.recvfrom(1024)[0])["seq"], 1)
                        client.sendto(encode(packet(seq=1)), server.getsockname())
                        client.sendto(encode(packet(seq=2)), server.getsockname())
                        self.assertEqual(json.loads(client.recvfrom(1024)[0])["seq"], 2)
                finally:
                    worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(observer.sequences, [1, 2])
        self.assertGreater(observer.ticks, 0)

    def test_udp_preview_calibration_motion_and_loss_quality(self):
        preview = TrackerPreview(config(calibration_seconds=0, minimum_samples=2), summary_only=True)
        results = []
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(("127.0.0.1", 0))
            worker = threading.Thread(target=lambda: results.append(
                serve(server, 0.4, 10.0, observer=preview)))
            with mock.patch("pose_receiver.OscOutput", side_effect=AssertionError("OSC opened")) as osc:
                with contextlib.redirect_stdout(io.StringIO()):
                    worker.start()
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                            client.settimeout(1)
                            for seq in (1, 2, 3, 4):
                                value = packet(seq=seq, detected=seq != 4)
                                if seq != 4:
                                    value.update(pose(right_lift=0.3 if seq == 3 else 0.0))
                                client.sendto(encode(value), server.getsockname())
                                self.assertEqual(json.loads(client.recvfrom(1024)[0])["seq"], seq)
                    finally:
                        worker.join(timeout=2)
                osc.assert_not_called()
            self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].accepted, 4)
        self.assertEqual(results[0].osc_updates, 0)
        self.assertEqual(preview.summary(), {
            "accepted_frames": 4, "pose_frames": 3, "transform_frames": 1,
            "transform_frame_pct": 25.0, "sessions": 1, "calibrations": 1,
            "tracking_losses": 1, "rejection_frames": {"no_person": 1},
            "blocked_landmark_frames": {},
        })

    def test_cli_requires_calibration_inputs(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--hip-height", "0.9", "--mirror", "yes"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--hip-height", "0.9", "--mirror", "yes", "--forward-sign", "1",
                  "--bind", "0.0.0.0"])

    def test_cli_preview_does_not_construct_osc_output(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        with mock.patch("pose_receiver.OscOutput", side_effect=AssertionError("OSC opened")) as osc:
            with contextlib.redirect_stdout(io.StringIO()):
                result = main(["--bind", "127.0.0.1", "--port", str(port),
                               "--hip-height", "0.9", "--mirror", "yes",
                               "--forward-sign", "-1", "--swap-left-right",
                               "--duration", "0.1", "--summary-only"])
        self.assertEqual(result, 0)
        osc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
