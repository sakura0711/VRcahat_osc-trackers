import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from android_replay import MODEL_HASHES, load_replay, main, summarize
from inspect_pose_pairs import read_pairs
from test_inspect_pose_pairs import make_zip, pair
from test_offline_pose_compare import GROUPS, settings, stills


def fixture(source, synthetic=False, mode="IMAGE"):
    manifest, frames = read_pairs(source)
    identities = []
    for n, f in enumerate(frames, 1):
        p = f["metadata"]["packet"]
        identities.append({"index": n, "sourceFrameId": f["metadata"]["frameId"],
                           "imageSha256": f["metadata"]["image"]["sha256"],
                           "imageWidth": 3, "imageHeight": 2, "inputRotationDegrees": 90, "mirroredInput": False})
    cases = []
    for model in ("lite", "full"):
        results = []
        for f, identity in zip(frames, identities):
            p = f["metadata"]["packet"]
            results.append({**identity, "personDetected": True, "landmarks": p["landmarks"],
                            "worldLandmarks": p["worldLandmarks"], "inferenceElapsedMs": 1.25,
                            "inputTimestampMs": identity["sourceFrameId"] if mode == "VIDEO" else None,
                            "taskResultTimestampMs": identity["sourceFrameId"] if mode == "VIDEO" else None,
                            "frameworkTimestampMs": identity["sourceFrameId"] if mode == "VIDEO" else -9223372036854775})
        cases.append({"model": model, "modelAsset": f"pose_landmarker_{model}.task", "modelSha256": MODEL_HASHES[model],
                      "runningMode": mode, "requestedDelegate": "CPU", "configuredDelegate": "CPU",
                      "fallbackUsed": False, "status": "completed", "results": results})
    return {"format": "vrchat-track-android-replay", "version": 1, "tasksVisionVersion": "1.0.0",
            "oscOutputEnabled": False, "originalLiveStreamReconstructed": False,
            "runtime": {"synthetic": synthetic, "internetPermission": False, "cameraPermission": False,
                        "applicationId": "com.vrchattrack.replay"},
            "source": {"zipSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                       "captureSession": manifest["captureSession"], "frameCount": len(frames)},
            "sourceFrames": identities, "cases": cases}


class AndroidReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.report = self.root / "capture.zip", self.root / "replay.json"
        pairs = []
        for n, p in enumerate(stills(), 1):
            value = pair(n * 3000)
            value["packet"].update(p, imageWidth=3, imageHeight=2)
            pairs.append(value)
        make_zip(self.source, pairs)
        self.data = fixture(self.source)

    def save(self, data=None):
        self.report.write_text(json.dumps(data or self.data), encoding="utf-8")

    def test_same_image_results_reproduce_known_height_without_sockets_or_original_mutation(self):
        self.save()
        original = self.source.read_bytes()
        with mock.patch("socket.socket", side_effect=AssertionError("network opened")):
            result = summarize(self.source, self.report, GROUPS, [1, 2, 3], settings())
        self.assertFalse(result["synthetic"])
        self.assertEqual(len(result["candidates"]), 2)
        for c in result["candidates"]:
            self.assertTrue(c["geometry_comparison_complete"])
            self.assertAlmostEqual(c["own_calibration"]["changes_raised_minus"]["before"]["right_y_cm"], 20)
            self.assertAlmostEqual(c["phone_fixed_calibration"]["changes_raised_minus"]["after"]["right_y_cm"], 20)
        self.assertEqual(self.source.read_bytes(), original)

    def test_wrong_source_or_frame_cannot_be_joined(self):
        changes = [lambda d: d["source"].update(zipSha256="0" * 64),
                   lambda d: d["sourceFrames"][0].update(sourceFrameId=999),
                   lambda d: d["cases"][0]["results"][0].update(imageSha256="0" * 64),
                   lambda d: d["cases"][0]["results"].reverse(),
                   lambda d: d["cases"][0]["results"][0].update(index=True)]
        for change in changes:
            bad = copy.deepcopy(self.data); change(bad); self.save(bad)
            with self.subTest(change=change), self.assertRaises(ValueError):
                load_replay(self.source, self.report)

    def test_case_failure_is_preserved_and_cpu_fallback_is_rejected(self):
        self.data["cases"][1].update(status="error", errorKind="UnavailableGpu", results=[])
        self.data["cases"][1].pop("configuredDelegate")
        self.save()
        result = summarize(self.source, self.report, GROUPS, [1, 2, 3], settings())
        self.assertEqual(result["candidates"][1]["status"], "error")
        self.assertNotIn("own_calibration", result["candidates"][1])
        self.assertFalse(result["candidates"][1]["geometry_comparison_complete"])
        self.data["cases"][0]["fallbackUsed"] = True; self.save()
        with self.assertRaisesRegex(ValueError, "fallback"):
            load_replay(self.source, self.report)

    def test_no_pose_is_missing_data_and_not_previous_landmarks(self):
        row = self.data["cases"][0]["results"][3]
        row.update(personDetected=False, landmarks=[], worldLandmarks=[]); self.save()
        result = summarize(self.source, self.report, GROUPS, [1, 2, 3], settings())
        self.assertEqual(result["candidates"][0]["own_calibration"]["phases"]["raised"]["valid"], 1)
        self.assertFalse(result["candidates"][0]["geometry_comparison_complete"])
        row["worldLandmarks"] = stills()[0]["worldLandmarks"]; self.save()
        with self.assertRaises(ValueError): load_replay(self.source, self.report)

    def test_image_sentinel_is_diagnostic_and_cannot_be_used_as_video_time(self):
        self.save()
        self.assertEqual(len(load_replay(self.source, self.report)[2]), 2)
        self.data["cases"][0]["results"][0]["taskResultTimestampMs"] = -9223372036854775
        self.save()
        with self.assertRaisesRegex(ValueError, "IMAGE"): load_replay(self.source, self.report)

    def test_video_timestamps_case_counts_and_runtime_flags_fail_closed(self):
        video = fixture(self.source, mode="VIDEO"); self.save(video)
        self.assertEqual(len(load_replay(self.source, self.report)[2]), 2)
        changes = [lambda d: d["cases"][0]["results"][0].update(taskResultTimestampMs=1),
                   lambda d: d["cases"][0]["results"].pop(),
                   lambda d: d.update(oscOutputEnabled=True),
                   lambda d: d.update(originalLiveStreamReconstructed=True),
                   lambda d: d["runtime"].update(internetPermission=True),
                   lambda d: d["cases"][0].update(modelSha256="0" * 64),
                   lambda d: d["cases"][0]["results"][0].update(session="old-phone-session"),
                   lambda d: d["cases"][0].update(requestedDelegate="GPU"),
                   lambda d: d.update(cases=[[], {}])]
        for change in changes:
            bad = copy.deepcopy(video); change(bad); self.save(bad)
            with self.subTest(change=change), self.assertRaises(ValueError): load_replay(self.source, self.report)

    def test_synthetic_fixture_is_rejected_by_default_and_label_survives_explicit_allowance(self):
        self.data["runtime"]["synthetic"] = True; self.save()
        with self.assertRaisesRegex(ValueError, "synthetic"): load_replay(self.source, self.report)
        result = summarize(self.source, self.report, GROUPS, [1, 2, 3], settings(), allow_synthetic=True)
        self.assertTrue(result["synthetic"])

    def test_cli_never_overwrites_and_keeps_raw_files(self):
        self.save()
        original = self.report.read_bytes()
        output = self.root / "result.json"
        args = [str(self.source), str(self.report), "--before", "1-3", "--raised", "4-5", "--after", "6-7",
                "--hip-height", ".9", "--mirrored-input", "no", "--forward-sign", "1", "--output", str(output)]
        with mock.patch("socket.socket", side_effect=AssertionError("network opened")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(args), 0)
            saved = output.read_bytes()
            self.assertEqual(main(args), 1)
        self.assertEqual(output.read_bytes(), saved)
        self.assertEqual(self.report.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
