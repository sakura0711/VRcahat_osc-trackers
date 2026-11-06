import contextlib
import copy
import io
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from offline_pose_compare import frame_numbers, geometry_summary, inference_packet, main, validate_groups
from test_inspect_pose_pairs import make_zip, pair
from test_tracker_pose import config, pose
from tracker_pose import Calibration


GROUPS = {"before": [1, 2, 3], "raised": [4, 5], "after": [6, 7]}


def stills():
    values = []
    for n in range(1, 8):
        p = pose(right_lift=0.2 if n in GROUPS["raised"] else 0)
        p.update(resultTimestampMs=n * 3000, imageWidth=480, imageHeight=640, mirroredInput=False)
        values.append(p)
    return values


def settings(**kwargs):
    return config(calibration_seconds=0, minimum_samples=3, max_sample_gap_ms=5000,
                  loss_timeout_ms=5000, **kwargs)


class OfflineComparisonTests(unittest.TestCase):
    def test_known_20cm_stills_with_explicit_mirror_and_role_mapping(self):
        packets = stills()
        for p in packets:
            for point in p["worldLandmarks"]:
                point["x"] *= -1
            for field in ("landmarks", "worldLandmarks"):
                original = p[field]
                partners = {a: b for l, r in ((11, 12), (23, 24), (25, 26), (27, 28), (29, 30), (31, 32))
                            for a, b in ((l, r), (r, l))}
                p[field] = [original[partners.get(i, i)] for i in range(33)]
        before = copy.deepcopy(packets)
        with mock.patch("socket.socket", side_effect=AssertionError("opened socket")):
            result = geometry_summary(packets, GROUPS, [1, 2, 3],
                                      settings(mirrored_input=True, swap_left_right=True))
        self.assertEqual(result["status"], "ok")
        for baseline in ("before", "after"):
            self.assertAlmostEqual(result["changes_raised_minus"][baseline]["right_y_cm"], 20)
        self.assertEqual(result["phases"]["raised"]["valid"], 2)
        self.assertEqual(packets, before)

    def test_own_vs_reference_calibration_separates_global_scale(self):
        original = geometry_summary(stills(), GROUPS, [1, 2, 3], settings())
        packets = stills()
        for p in packets:
            for point in p["worldLandmarks"]:
                for axis in ("x", "y", "z"):
                    point[axis] *= 0.8
        own = geometry_summary(packets, GROUPS, [1, 2, 3], settings())
        fixed = geometry_summary(packets, GROUPS, [1, 2, 3], settings(),
                                 Calibration(**original["calibration"]))
        self.assertAlmostEqual(own["calibration"]["scale"], 1.25)
        self.assertAlmostEqual(own["changes_raised_minus"]["before"]["right_y_cm"], 20)
        self.assertAlmostEqual(fixed["changes_raised_minus"]["before"]["right_y_cm"], 16)

    def test_missing_frames_are_counted_and_never_filled_with_zero_or_previous_pose(self):
        packets = stills()
        packets[3]["landmarks"][28]["visibility"] = 0.1
        partial = geometry_summary(packets, GROUPS, [1, 2, 3], settings())
        self.assertEqual(partial["phases"]["raised"]["valid"], 1)
        self.assertAlmostEqual(partial["changes_raised_minus"]["before"]["right_y_cm"], 20)
        packets[4]["personDetected"] = False
        missing = geometry_summary(packets, GROUPS, [1, 2, 3], settings())
        self.assertEqual(missing["phases"]["raised"]["valid"], 0)
        self.assertEqual(missing["phases"]["raised"]["metrics"]["right_y_cm"], {"median": None, "count": 0})
        self.assertIsNone(missing["changes_raised_minus"]["before"]["right_y_cm"])
        packets[0]["landmarks"][28]["presence"] = 0.1
        failed = geometry_summary(packets, GROUPS, [1, 2, 3], settings())
        self.assertEqual(failed["status"], "calibration_failed")
        self.assertEqual(failed["reason"], "image_confidence")
        self.assertNotIn("calibration", failed)

    def test_new_inference_does_not_impersonate_source_phone_timing_or_network_session(self):
        source = {**stills()[0], "session": "old-phone-session", "captureMonotonicNs": 123,
                  "analysisStartMonotonicNs": 456, "inferenceMs": 99, "sendMonotonicNs": 789}
        original = copy.deepcopy(source)
        packet = inference_packet(source, "candidate.task", source["landmarks"], source["worldLandmarks"])
        for field in ("session", "captureMonotonicNs", "analysisStartMonotonicNs", "inferenceMs", "sendMonotonicNs"):
            self.assertNotIn(field, packet)
        self.assertEqual(packet["resultTimestampMs"], source["resultTimestampMs"])
        self.assertEqual(packet["modelAsset"], "candidate.task")
        self.assertEqual(source, original)
        with self.assertRaises(ValueError):
            inference_packet(source, "candidate.task", source["landmarks"], [])

    def test_phase_selection_rejects_overlap_duplicates_and_non_neutral_calibration(self):
        self.assertEqual(frame_numbers("3-5,7"), [3, 4, 5, 7])
        for text in ("0", "5-3", "1-41", "3,3", "", "-1"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                frame_numbers(text)
        for groups, calibration in (({**GROUPS, "raised": [3, 4]}, [1, 2, 3]),
                                    (GROUPS, [1, 4]), (GROUPS, [1, 2, 3, 8])):
            with self.assertRaises(ValueError):
                validate_groups(groups, calibration, 7)

    def test_cli_new_inferences_are_separate_and_output_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, model, output = root / "capture.zip", root / "local.task", root / "result"
            pairs = []
            for n, packet in enumerate(stills(), 1):
                value = pair(frame_id=n * 3000)
                value["packet"].update(packet, imageWidth=3, imageHeight=2)
                pairs.append(value)
            make_zip(source, pairs)
            model.write_bytes(b"test-only local model; inference mocked")
            source_before = source.read_bytes()
            args = [str(source), "--model", f"test={model}", "--before", "1-3", "--raised", "4-5",
                    "--after", "6-7", "--hip-height", ".9", "--mirrored-input", "no",
                    "--forward-sign", "1", "--output", str(output)]
            with mock.patch("offline_pose_compare.rerun_images", return_value=stills()) as infer, \
                    mock.patch("offline_pose_compare.importlib.metadata.version", return_value="test-runtime"), \
                    mock.patch("socket.socket", side_effect=AssertionError("network opened")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 0)
                saved = (output / "summary.json").read_bytes()
                self.assertEqual(main(args), 1)
                self.assertEqual(infer.call_count, 1)
            self.assertEqual((output / "summary.json").read_bytes(), saved)
            self.assertEqual(source.read_bytes(), source_before)
            generated = json.loads((output / "test-inferences.json").read_text())
            self.assertIn("not original phone packets", generated["kind"])
            self.assertEqual(generated["source_images"][0]["source_frame_id"], 3000)
            self.assertEqual(json.loads(saved)["osc_packets"], 0)

    def test_cli_network_guard_blocks_socket_without_breaking_ssl_import(self):
        code = ("import sys; from offline_pose_compare import deny_network; "
                "sys.addaudithook(deny_network); import ssl, socket; socket.socket()")
        result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True,
                                cwd=Path(__file__).parent, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("offline comparison forbids network sockets", result.stderr)
        self.assertNotIn("TypeError", result.stderr)


if __name__ == "__main__":
    unittest.main()
