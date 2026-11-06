import contextlib
import copy
import hashlib
import io
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import warnings
import zipfile
import zlib
from pathlib import Path
from unittest import mock

from inspect_pose_pairs import attach_recording, main, png_dimensions, read_pairs, render_viewer, validate_pair
from pose_receiver import validate_packet
from test_pose_receiver import encode, packet


def png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    # 3 x 2 RGBA pixels, distinct red and blue corners.
    pixels = b"\0" + bytes([255, 0, 0, 255]) * 3 + b"\0" + bytes([0, 0, 255, 255]) * 3
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 3, 2, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


def pair(frame_id=11):
    source = packet(seq=frame_id)
    source.update(resultTimestampMs=frame_id, imageWidth=3, imageHeight=2, inputRotationDegrees=90,
                  mirroredInput=True, modelAsset="pose_landmarker_lite.task")
    source["analysisStartMonotonicNs"] += frame_id
    source["captureMonotonicNs"] += frame_id
    source["landmarks"][27].update(x=0.25, y=0.75)
    return {"format": "vrchat-track-image-pair", "version": 1, "captureSession": "session",
            "frameId": frame_id, "image": {"file": "input.png", "sha256": hashlib.sha256(png()).hexdigest()},
            "packet": source}


def make_zip(path, pairs=None, extra=None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "vrchat-track-image-pairs", "version": 1,
                                                     "captureSession": "session"}))
        for index, value in enumerate(pairs or [pair()], 1):
            archive.writestr(f"frame-{index:04}/input.png", png())
            archive.writestr(f"frame-{index:04}/landmarks.json", json.dumps(value))
        for name, data in (extra or {}).items():
            archive.writestr(name, data)


class ImagePairTests(unittest.TestCase):
    def test_image_hash_dimensions_and_frame_identity_are_bound(self):
        value = pair()
        self.assertEqual(png_dimensions(png()), (3, 2))
        validate_pair(value, png(), "session")
        self.assertEqual(validate_packet(encode(value["packet"])), value["packet"])
        changes = [lambda p: p.update(frameId=12),
                   lambda p: p.update(captureSession="other"),
                   lambda p: p["image"].update(sha256="0" * 64),
                   lambda p: p["packet"].update(imageWidth=2),
                   lambda p: p["packet"].update(resultTimestampMs=True),
                   lambda p: p["packet"].update(inputRotationDegrees=False),
                   lambda p: p["packet"]["worldLandmarks"][0].update(x=float("nan"))]
        for change in changes:
            with self.subTest(change=change):
                bad = copy.deepcopy(value)
                change(bad)
                with self.assertRaises(ValueError):
                    validate_pair(bad, png(), "session")
        damaged = bytearray(png())
        damaged[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum"):
            png_dimensions(bytes(damaged))

    def test_zip_and_directory_reader_use_same_sources_without_sockets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "capture.zip"
            make_zip(archive)
            with mock.patch("socket.socket", side_effect=AssertionError("network opened")):
                manifest, frames = read_pairs(archive)
                extracted = root / "export"
                with zipfile.ZipFile(archive) as source:
                    source.extractall(extracted)  # Only the known synthetic fixture.
                self.assertEqual(read_pairs(extracted), (manifest, frames))
            self.assertEqual(frames[0]["metadata"]["packet"], pair()["packet"])

    def test_duplicate_frames_and_unsafe_archives_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "capture.zip"
            make_zip(archive, [pair(), pair()])
            with self.assertRaisesRegex(ValueError, "duplicate frame"):
                read_pairs(archive)
            make_zip(archive, extra={"../outside.txt": "invalid"})
            with self.assertRaisesRegex(ValueError, "paths"):
                read_pairs(archive)
            make_zip(archive)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(archive, "a") as source:
                    source.writestr("frame-0001/input.png", png())
            with self.assertRaisesRegex(ValueError, "duplicate entries"):
                read_pairs(archive)
            self.assertFalse((Path(directory).parent / "outside.txt").exists())

    def test_tracker_join_requires_exact_frame_timestamps_and_sources(self):
        value = pair()
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "tracker.jsonl"
            row = {"type": "frame", "packet": copy.deepcopy(value["packet"]), "at_ns": 1234,
                   "transforms": {"right_foot": {"position": [0.1, 0.2, 0.3], "rotation": [0, 0, 0]}}}
            log.write_text(json.dumps(row) + "\n", encoding="utf-8")
            frames = [{"metadata": value}]
            attach_recording(frames, log)
            self.assertEqual(frames[0]["tracker_record"]["transforms"], row["transforms"])
            for field in ("landmarks", "mirroredInput"):
                bad = copy.deepcopy(row)
                if field == "landmarks":
                    bad["packet"][field][27]["y"] += 0.01
                else:
                    bad["packet"][field] = False
                log.write_text(json.dumps(bad) + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "sources|landmarks"):
                    attach_recording(frames, log)
            log.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                attach_recording(frames, log)

    def test_wrong_run_recording_is_rejected_instead_of_silently_joined(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "different-run.jsonl"
            value = pair()
            other = copy.deepcopy(value["packet"])
            other["captureMonotonicNs"] += 1
            log.write_text(json.dumps({"type": "frame", "packet": other}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no same-frame"):
                attach_recording([{"metadata": value}], log)

    def test_no_pose_image_is_valid_and_not_filled_with_old_points(self):
        value = pair()
        value["packet"].update(personDetected=False, landmarks=[], worldLandmarks=[])
        validate_pair(value, png(), "session")
        value["packet"]["landmarks"] = pair()["packet"]["landmarks"]
        with self.assertRaisesRegex(ValueError, "count"):
            validate_pair(value, png(), "session")

    def test_viewer_keeps_source_coordinates_and_escapes_metadata(self):
        value = pair()
        value["packet"]["modelAsset"] = "</script><script>alert(1)</script>"
        frames = [{"metadata": value, "png_base64": "test"}]
        html = render_viewer(frames, swap_left_right=True)
        encoded = html.split('<script id="payload" type="application/json">', 1)[1].split("</script>", 1)[0]
        payload = json.loads(encoded)
        self.assertEqual(payload["frames"], frames)
        self.assertEqual(payload["roles"]["右踝"], 27)
        self.assertEqual(payload["frames"][0]["metadata"]["packet"]["landmarks"][27]["x"], 0.25)
        self.assertIn("default-src 'none'", html)
        self.assertNotIn("</script><script>alert", html)

    @unittest.skipUnless(shutil.which("node"), "Node is optional for viewer logic verification")
    def test_generated_viewer_coordinates_and_async_frame_switching(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = pair(), pair(12)
            second["packet"]["landmarks"][27].update(x=0.75, y=0.25)
            frames = [{"metadata": p, "png_base64": "synthetic"} for p in (first, second)]
            output = Path(directory) / "viewer.html"
            output.write_text(render_viewer(frames, True), encoding="utf-8")
            result = subprocess.run([shutil.which("node"), str(Path(__file__).with_name("check_pose_pair_viewer.js")),
                                     str(output)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("stale image load rejected", result.stdout)

    def test_cli_creates_local_viewer_without_network_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, output = Path(directory) / "capture.zip", Path(directory) / "viewer.html"
            make_zip(archive)
            with mock.patch("socket.socket", side_effect=AssertionError("network opened")), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(archive), "--output", str(output), "--swap-left-right"]), 0)
                first = output.read_bytes()
                self.assertEqual(main([str(archive), "--output", str(output)]), 1)
            self.assertEqual(output.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
