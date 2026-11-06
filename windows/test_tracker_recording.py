import contextlib
import copy
import io
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from pose_receiver import serve
from test_pose_receiver import encode, packet
from test_tracker_pose import config, pose
from tracker_pose import SWAPPED_LANDMARKS
from tracker_preview import TrackerPreview, main
from tracker_recording import TrackerRecording, replay_recording


def phone_frame(seq, *, lift=0.0, session="first", reflected=False):
    value = packet(seq=seq, session=session)
    value.update(pose(right_lift=lift))
    for index, point in enumerate(value["landmarks"]):
        point.update(x=index / 40, y=seq / 100 + index / 1000)
    if reflected:
        for point in value["worldLandmarks"]:
            point["x"] *= -1
            point["z"] *= -1
        for name in ("landmarks", "worldLandmarks"):
            points = value[name]
            value[name] = [points[SWAPPED_LANDMARKS.get(i, i)] for i in range(33)]
    return value


class TrackerRecordingTests(unittest.TestCase):
    def test_same_packet_sources_survive_throttling_side_mapping_loss_and_new_session(self):
        cfg = config(mirrored_input=True, swap_left_right=True, forward_sign=-1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            inputs = []
            with TrackerRecording(path, cfg) as recording, contextlib.redirect_stdout(io.StringIO()):
                preview = TrackerPreview(cfg, display_interval_s=100, summary_only=True, recording=recording)
                for seq in range(1, 6):
                    value = phone_frame(seq, lift=0.2 if seq == 4 else 0, reflected=True)
                    if seq == 5:
                        value["landmarks"][27]["visibility"] = 0.1
                    inputs.append(copy.deepcopy(value))
                    preview.on_packet(value, (seq - 1) * 100_000_000)
                    self.assertEqual(value, inputs[-1])
                preview.tick(650_000_001)
                for seq in range(1, 5):
                    value = phone_frame(seq, session="second", lift=0.2 if seq == 4 else 0, reflected=True)
                    inputs.append(copy.deepcopy(value))
                    preview.on_packet(value, 600_000_000 + seq * 100_000_000)
                preview.report_final()
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0]["source_indices"]["right_ankle"], 27)
            self.assertEqual(records[0]["config"]["mirrored_input"], True)
            frames = [r for r in records if r["type"] == "frame"]
            self.assertEqual([r["packet"] for r in frames], inputs)
            self.assertEqual(len(frames), 9)
            self.assertEqual(frames[3]["at_ns"], 300_000_000)
            self.assertAlmostEqual(frames[3]["transforms"]["right_foot"]["position"][1], 0.28)
            for index in (0, 1, 2, 4, 5, 6, 7):
                self.assertEqual(frames[index]["transforms"], {})
                self.assertIsNone(frames[index]["height_diagnostics"])
            with mock.patch("socket.socket", side_effect=AssertionError("replay opened a socket")):
                self.assertEqual(replay_recording(path),
                                 {"frames": 9, "transform_frames": 2, "ticks": 1, "summaries": 1})
            frames[3]["transforms"]["right_foot"]["position"][1] += 0.01
            path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "replay mismatch"):
                replay_recording(path)

    def test_existing_measurement_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            path.write_text("existing measurement", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                TrackerRecording(path, config())
            self.assertEqual(path.read_text(encoding="utf-8"), "existing measurement")

    def test_cli_recording_is_explicit_and_constructs_no_osc_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as available:
                available.bind(("127.0.0.1", 0))
                port = available.getsockname()[1]
            with mock.patch("pose_receiver.OscOutput", side_effect=AssertionError("OSC opened")) as osc:
                with mock.patch("tracker_output.TrackerOutput", side_effect=AssertionError("tracker OSC opened")) as tracker:
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = main(["--port", str(port), "--hip-height", "0.9", "--mirror", "no",
                                       "--forward-sign", "1", "--duration", "0.01", "--summary-only",
                                       "--record", str(path)])
                osc.assert_not_called()
                tracker.assert_not_called()
            self.assertEqual(result, 0)
            self.assertEqual(replay_recording(path)["frames"], 0)
            self.assertEqual(replay_recording(path)["summaries"], 1)

    def test_udp_recording_contains_only_accepted_packets_and_zero_osc_updates(self):
        cfg = config(calibration_seconds=0, minimum_samples=2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            results = []
            with TrackerRecording(path, cfg) as recording:
                preview = TrackerPreview(cfg, summary_only=True, recording=recording)
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
                    server.bind(("127.0.0.1", 0))
                    worker = threading.Thread(target=lambda: results.append(
                        serve(server, 0.4, 10.0, observer=preview)))
                    with mock.patch("pose_receiver.OscOutput", side_effect=AssertionError("OSC opened")):
                        with contextlib.redirect_stdout(io.StringIO()):
                            worker.start()
                            try:
                                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                                    client.settimeout(1)
                                    client.sendto(b"invalid JSON", server.getsockname())
                                    for seq in (1, 2, 3, 4):
                                        if seq == 2:
                                            client.sendto(encode(phone_frame(1)), server.getsockname())
                                        value = phone_frame(seq, lift=0.2 if seq == 3 else 0)
                                        client.sendto(encode(value), server.getsockname())
                                        self.assertEqual(json.loads(client.recvfrom(1024)[0])["seq"], seq)
                            finally:
                                worker.join(timeout=2)
                            preview.report_final()
                    self.assertFalse(worker.is_alive())
            self.assertEqual(results[0].accepted, 4)
            self.assertEqual(results[0].malformed, 1)
            self.assertEqual(results[0].out_of_order, 1)
            self.assertEqual(results[0].osc_updates, 0)
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["packet"]["seq"] for r in records if r["type"] == "frame"], [1, 2, 3, 4])
            self.assertEqual(replay_recording(path)["frames"], 4)


if __name__ == "__main__":
    unittest.main()
