"""Compare saved phone landmarks with CPU IMAGE reruns of local model files.

Research only: sparse photos cannot reproduce a phone LIVE_STREAM pipeline.
No downloads, receiver, OSC output, runtime calibration changes or image edits.
MediaPipe and its image dependencies are optional; ordinary tests do not need them.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.metadata
import json
import math
import re
import statistics
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from inspect_pose_pairs import _point_arrays, read_pairs
from pose_control import point_confident
from tracker_pose import TrackerCalibrationConfig, TrackerPoseCalibrator

METRICS = ("right_y_cm", "left_y_cm", "right_pre_floor_cm", "floor_shift_cm", "ankle_gap_cm",
           "image_ankle_gap_px", "right_thigh_cm", "right_shin_cm", "shoulder_cm")


def frame_numbers(value: str) -> list[int]:
    result = []
    for part in value.split(","):
        if not re.fullmatch(r"[1-9]\d*(?:-[1-9]\d*)?", part):
            raise ValueError("frames must be positive numbers or ascending ranges")
        ends = [int(x) for x in part.split("-")]
        start, end = ends[0], ends[-1]
        if not start <= end <= 40:
            raise ValueError("frame range must be ascending and within 1..40")
        result.extend(range(start, end + 1))
    if len(set(result)) != len(result):
        raise ValueError("duplicate frame number")
    return sorted(result)


def validate_groups(groups: dict[str, list[int]], calibration: list[int], count: int) -> None:
    selected = [n for values in groups.values() for n in values]
    if (set(groups) != {"before", "raised", "after"} or any(not values for values in groups.values()) or len(calibration) < 2 or
            any(type(n) is not int or not 1 <= n <= count for n in selected + calibration)):
        raise ValueError("missing or out-of-range phase/calibration frames")
    if len(set(selected)) != len(selected) or len(set(calibration)) != len(calibration):
        raise ValueError("phases must not overlap or contain duplicate frames")
    if not set(calibration).issubset(groups["before"]):
        raise ValueError("calibration frames must be in the before phase")


def geometry_summary(packets: list[dict], groups: dict[str, list[int]],
                     calibration_frames: list[int], config: TrackerCalibrationConfig,
                     fixed_calibration=None) -> dict:
    """Apply one fixed calibration to independent stills, bypassing live timing only.

    Neutral samples still go through ingest's confidence, feet-level and axis gates.
    _frame/_transforms are deliberately used after calibration: stills have no live
    availability semantics. Invalid samples stay missing; they never become zero.
    """
    validate_groups(groups, calibration_frames, len(packets))
    controller = TrackerPoseCalibrator(config)
    if fixed_calibration is None:
        for n in calibration_frames:
            packet = packets[n - 1]
            controller.ingest(packet, packet["resultTimestampMs"] * 1_000_000)
            if controller.calibration is None and (not controller.samples or controller.last_valid_ns is None):
                return {"status": "calibration_failed", "frame": n,
                        "reason": controller.diagnostic.reason}
        if controller.calibration is None:
            return {"status": "calibration_failed", "reason": controller.diagnostic.reason}
    else:
        controller.calibration = fixed_calibration
    right_ankle, left_ankle = (27, 28) if config.swap_left_right else (28, 27)
    right_hip, right_knee = (23, 25) if config.swap_left_right else (24, 26)
    rows = []
    for n, packet in enumerate(packets, 1):
        controller.height_diagnostics = None
        frame = controller._frame(packet)
        transforms = controller._transforms(frame) if frame is not None else {}
        if not transforms:
            rows.append({"frame": n, "reason": controller.diagnostic.reason})
            continue
        diagnostic = controller.height_diagnostics
        normalized, world = packet["landmarks"], packet["worldLandmarks"]

        def segment_cm(a, b):
            if not all(point_confident(normalized[i], config.confidence) for i in (a, b)):
                return None
            if any(w.get(k) is not None and w[k] < config.confidence
                   for i in (a, b) for w in (world[i],) for k in ("visibility", "presence")):
                return None
            return math.dist([world[a][k] for k in ("x", "y", "z")],
                             [world[b][k] for k in ("x", "y", "z")]) * 100

        rows.append({
            "frame": n, "reason": "valid",
            "right_y_cm": transforms["right_foot"].position[1] * 100,
            "left_y_cm": transforms["left_foot"].position[1] * 100,
            "right_pre_floor_cm": diagnostic.ankle_relative_y_m[1] * 100,
            "floor_shift_cm": diagnostic.floor_shift_m * 100,
            "ankle_gap_cm": sum(diagnostic.vertical_components_m) * 100,
            "image_ankle_gap_px": (normalized[right_ankle]["y"] -
                                    normalized[left_ankle]["y"]) * packet["imageHeight"],
            "right_thigh_cm": segment_cm(right_hip, right_knee),
            "right_shin_cm": segment_cm(right_knee, right_ankle),
            "shoulder_cm": segment_cm(11, 12),
        })
    phases = {}
    for name, numbers in groups.items():
        valid = [rows[n - 1] for n in numbers if rows[n - 1]["reason"] == "valid"]
        metrics = {}
        for key in METRICS:
            values = [r[key] for r in valid if r.get(key) is not None]
            metrics[key] = {"median": statistics.median(values) if values else None,
                            "count": len(values)}
        phases[name] = {"selected": len(numbers), "valid": len(valid), "metrics": metrics}
    changes = {}
    for baseline in ("before", "after"):
        comparison = {}
        for key in ("right_y_cm", "right_pre_floor_cm", "floor_shift_cm", "ankle_gap_cm"):
            a = phases["raised"]["metrics"].get(key, {}).get("median")
            b = phases[baseline]["metrics"].get(key, {}).get("median")
            comparison[key] = a - b if a is not None and b is not None else None
        changes[baseline] = comparison
    return {"status": "ok", "calibration": asdict(controller.calibration),
            "phases": phases, "changes_raised_minus": changes,
            "frame_reasons": dict(Counter(row["reason"] for row in rows)), "frames": rows}


def inference_packet(source: dict, model_name: str, normalized: list[dict], world: list[dict]) -> dict:
    # Only source-image geometry/ordering metadata is retained. Old network
    # session, camera timing, inference duration and send timing are not CPU results.
    packet = {k: copy.deepcopy(source[k]) for k in (
        "resultTimestampMs", "imageWidth", "imageHeight", "inputRotationDegrees", "mirroredInput")
        if k in source}
    packet.update(personDetected=bool(normalized), modelAsset=model_name,
                  landmarks=normalized, worldLandmarks=world)
    _point_arrays(packet)
    return packet


def rerun_images(frames: list[dict], model: Path) -> list[dict]:
    # Lazy imports keep the standard-library test suite independent of MediaPipe.
    import cv2
    import mediapipe as mp
    import numpy as np

    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model.resolve()),
                                         delegate=mp.tasks.BaseOptions.Delegate.CPU),
        running_mode=mp.tasks.vision.RunningMode.IMAGE, num_poses=1,
        min_pose_detection_confidence=0.5, min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5)
    packets = []
    with mp.tasks.vision.PoseLandmarker.create_from_options(options) as landmarker:
        for frame in frames:
            decoded = cv2.imdecode(np.frombuffer(base64.b64decode(frame["png_base64"]), dtype=np.uint8),
                                   cv2.IMREAD_COLOR)
            image = mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB))
            result = landmarker.detect(image)
            # Source identities remain in the enclosing record, not a fake phone
            # recording. These arrays are NEW inferences, never same-frame joins.
            converted = {}
            for key, arrays in (("landmarks", result.pose_landmarks),
                                ("worldLandmarks", result.pose_world_landmarks)):
                converted[key] = [{k: (float(getattr(p, k)) if getattr(p, k) is not None else None)
                                   for k in ("x", "y", "z", "visibility", "presence")}
                                  for p in arrays[0]] if arrays else []
            packets.append(inference_packet(frame["metadata"]["packet"], model.name,
                                            converted["landmarks"], converted["worldLandmarks"]))
    return packets


def deny_network(event, args):
    # Audit hook does not replace socket.socket's type (SSL subclasses it).
    if event in ("socket.__new__", "socket.connect", "socket.sendto", "socket.getaddrinfo"):
        raise RuntimeError("offline comparison forbids network sockets")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--model", action="append", required=True, help="unique NAME=local-model.task")
    parser.add_argument("--before", required=True, help="one-based frame numbers, e.g. 3-7")
    parser.add_argument("--raised", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--calibration", help="subset of before; defaults to before")
    parser.add_argument("--hip-height", type=float, required=True)
    parser.add_argument("--mirrored-input", choices=("yes", "no"), required=True)
    parser.add_argument("--swap-left-right", action="store_true")
    parser.add_argument("--forward-sign", type=int, choices=(-1, 1), required=True)
    parser.add_argument("--yaw", type=float, default=0)
    parser.add_argument("--output", type=Path, required=True, help="new local directory; never overwrites")
    args = parser.parse_args(argv)
    try:
        manifest, frames = read_pairs(args.source)
        groups = {key: frame_numbers(getattr(args, key)) for key in ("before", "raised", "after")}
        calibration = frame_numbers(args.calibration) if args.calibration else groups["before"]
        validate_groups(groups, calibration, len(frames))
        config = TrackerCalibrationConfig(args.hip_height, args.yaw, args.mirrored_input == "yes",
                                          args.forward_sign, calibration_seconds=0,
                                          minimum_samples=len(calibration), max_sample_gap_ms=5000,
                                          loss_timeout_ms=5000, swap_left_right=args.swap_left_right)
        models = {}
        for argument in args.model:
            name, sep, path = argument.partition("=")
            if not sep or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name) or name in models:
                raise ValueError("models require unique simple NAME=PATH labels")
            models[name] = Path(path)
            if not models[name].is_file():
                raise ValueError("local model file does not exist")
        if any(f["metadata"]["packet"]["mirroredInput"] != config.mirrored_input for f in frames):
            raise ValueError("mirror setting does not match saved image metadata")
        original = [f["metadata"]["packet"] for f in frames]
        source_summary = geometry_summary(original, groups, calibration, config)
        if source_summary["status"] != "ok":
            raise ValueError("selected phone calibration failed: " + json.dumps(source_summary))
        from tracker_pose import Calibration
        fixed = Calibration(**source_summary["calibration"])
        args.output.mkdir(parents=True, exist_ok=False)
        report = {"format": "vrchat-track-offline-model-comparison", "version": 1,
                  "capture_session": manifest["captureSession"],
                  "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest() if args.source.is_file() else None,
                  "groups": groups, "calibration_frames": calibration, "config": asdict(config),
                  "mode": "independent IMAGE", "delegate": "CPU", "osc_packets": 0,
                  "warning": "Not phone LIVE_STREAM replay, camera/metric ground truth or live timeout acceptance.",
                  "phone_recorded": source_summary, "models": {}}
        for name, model in models.items():
            packets = rerun_images(frames, model)
            with (args.output / (name + "-inferences.json")).open("x", encoding="utf-8") as output:
                json.dump({"kind": "new desktop CPU IMAGE inferences, not original phone packets",
                           "source_images": [{"source_frame_id": f["metadata"]["frameId"],
                                              "image_sha256": f["metadata"]["image"]["sha256"]}
                                             for f in frames], "inference_packets": packets}, output, allow_nan=False)
            report["models"][name] = {
                "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                "bytes": model.stat().st_size, "mediapipe_version": importlib.metadata.version("mediapipe"),
                "own_calibration": geometry_summary(packets, groups, calibration, config),
                "phone_fixed_calibration": geometry_summary(packets, groups, calibration, config, fixed)}
            print("MODEL_COMPLETE " + name, flush=True)
        with (args.output / "summary.json").open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, ensure_ascii=False, allow_nan=False)
        print(f"OFFLINE_COMPARISON_COMPLETE output={args.output}; no OSC.")
        return 0
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print(f"offline comparison error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.addaudithook(deny_network)
    raise SystemExit(main())
