"""Verify Android replay JSON against the exact original image ZIP; no sockets/OSC."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

from inspect_pose_pairs import _point_arrays, read_pairs
from offline_pose_compare import deny_network, frame_numbers, geometry_summary, inference_packet
from tracker_pose import Calibration, TrackerCalibrationConfig

MODEL_HASHES = {
    "lite": "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
    "full": "4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad",
}


def identity(frame: dict, index: int) -> dict:
    meta = frame["metadata"]
    p = meta["packet"]
    return {"index": index, "sourceFrameId": meta["frameId"], "imageSha256": meta["image"]["sha256"],
            "imageWidth": p["imageWidth"], "imageHeight": p["imageHeight"],
            "inputRotationDegrees": p["inputRotationDegrees"], "mirroredInput": p["mirroredInput"]}


def check_identity(row: dict, expected: dict) -> None:
    if (not isinstance(row, dict) or any(type(row.get(k)) is not int for k in
            ("index", "sourceFrameId", "imageWidth", "imageHeight", "inputRotationDegrees")) or
            type(row.get("mirroredInput")) is not bool or any(row.get(k) != v for k, v in expected.items())):
        raise ValueError("source image/frame identity mismatch")


def load_replay(source: Path, report_path: Path, *, allow_synthetic: bool = False):
    manifest, frames = read_pairs(source)
    if not source.is_file() or report_path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("requires original ZIP and bounded replay JSON")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (not isinstance(report, dict) or report.get("format") != "vrchat-track-android-replay" or type(report.get("version")) is not int or
            report["version"] != 1 or report.get("tasksVisionVersion") != "1.0.0" or
            report.get("oscOutputEnabled") is not False or report.get("originalLiveStreamReconstructed") is not False):
        raise ValueError("unsupported replay format/runtime or output flags")
    runtime = report["runtime"]
    if (not isinstance(runtime, dict) or type(runtime.get("synthetic")) is not bool or runtime.get("internetPermission") is not False or
            runtime.get("cameraPermission") is not False or runtime.get("applicationId") != "com.vrchattrack.replay"):
        raise ValueError("invalid replay runtime identity/permissions")
    if runtime["synthetic"] and not allow_synthetic:
        raise ValueError("synthetic replay requires explicit test-only allowance")
    descriptor = report["source"]
    if (not isinstance(descriptor, dict) or descriptor.get("zipSha256") != hashlib.sha256(source.read_bytes()).hexdigest() or
            descriptor.get("captureSession") != manifest["captureSession"] or
            type(descriptor.get("frameCount")) is not int or descriptor["frameCount"] != len(frames)):
        raise ValueError("original source ZIP/session mismatch")
    identities = [identity(frame, n) for n, frame in enumerate(frames, 1)]
    if not isinstance(report.get("sourceFrames"), list) or len(report["sourceFrames"]) != len(frames):
        raise ValueError("incomplete source frame identities")
    for row, expected in zip(report["sourceFrames"], identities):
        check_identity(row, expected)
    cases = report.get("cases")
    if (not isinstance(cases, list) or len(cases) != 2 or not all(isinstance(c, dict) for c in cases) or
            {c.get("model") for c in cases} != {"lite", "full"}):
        raise ValueError("requires exactly one Lite and one Full case")
    plans = set()
    candidates = []
    for case in cases:
        model, mode, delegate = case["model"], case.get("runningMode"), case.get("requestedDelegate")
        if (mode not in ("IMAGE", "VIDEO") or delegate not in ("CPU", "GPU") or
                case.get("fallbackUsed") is not False or case.get("modelSha256") != MODEL_HASHES[model] or
                case.get("modelAsset") != f"pose_landmarker_{model}.task"):
            raise ValueError("invalid replay model/mode/delegate or silent fallback")
        plans.add((mode, delegate))
        candidate = {"name": f"android_{model}_{delegate.lower()}_{mode.lower()}", "model": model,
                     "mode": mode, "delegate": delegate, "status": case.get("status")}
        if case.get("status") == "error":
            if case.get("results") != [] or case.get("configuredDelegate") is not None or not isinstance(case.get("errorKind"), str):
                raise ValueError("failed case must not contain usable inference results")
            candidate["errorKind"] = case["errorKind"]
        elif case.get("status") == "completed":
            rows = case.get("results")
            if (case.get("configuredDelegate") != delegate or not isinstance(rows, list) or len(rows) != len(frames)):
                raise ValueError("incomplete/mislabeled replay case")
            packets = []
            for frame, expected, row in zip(frames, identities, rows):
                check_identity(row, expected)
                task_time, elapsed = row.get("taskResultTimestampMs"), row.get("inferenceElapsedMs")
                if (type(elapsed) not in (int, float) or
                        not math.isfinite(elapsed) or elapsed < 0 or any(k in row for k in
                        ("session", "seq", "captureMonotonicNs", "analysisStartMonotonicNs", "sendMonotonicNs"))):
                    raise ValueError("invalid replay timing/identity")
                if mode == "VIDEO":
                    if (type(task_time) is not int or type(row.get("inputTimestampMs")) is not int or
                            row["inputTimestampMs"] != expected["sourceFrameId"] or task_time != row["inputTimestampMs"]):
                        raise ValueError("VIDEO result timestamp mismatch")
                elif row.get("inputTimestampMs") is not None or task_time is not None:
                    raise ValueError("IMAGE must not pretend to replay video timestamps")
                if "frameworkTimestampMs" in row and type(row["frameworkTimestampMs"]) is not int:
                    raise ValueError("invalid diagnostic framework timestamp")
                _point_arrays(row)
                packets.append(inference_packet(frame["metadata"]["packet"], case["modelAsset"],
                                                row["landmarks"], row["worldLandmarks"]))
            candidate["packets"] = packets
        else:
            raise ValueError("unsupported replay status")
        candidates.append(candidate)
    if len(plans) != 1:
        raise ValueError("Lite/Full must use the same mode and delegate")
    return report, frames, candidates


def summarize(source: Path, report_path: Path, groups: dict, calibration: list[int],
              config: TrackerCalibrationConfig, *, allow_synthetic: bool = False) -> dict:
    report, frames, candidates = load_replay(source, report_path, allow_synthetic=allow_synthetic)
    if any(f["metadata"]["packet"]["mirroredInput"] != config.mirrored_input for f in frames):
        raise ValueError("mirror setting does not match original PNG metadata")
    original = geometry_summary([f["metadata"]["packet"] for f in frames], groups, calibration, config)
    if original["status"] != "ok":
        raise ValueError("original neutral calibration failed")
    reference = Calibration(**original["calibration"])
    result = {"format": "vrchat-track-android-replay-summary", "version": 1,
              "synthetic": report["runtime"]["synthetic"], "runtime": report["runtime"],
              "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
              "source_zip_sha256": report["source"]["zipSha256"], "osc_packets": 0,
              "warning": "Sparse replay diagnostics; not original LIVE_STREAM or metric/FBT acceptance.",
              "phone_recorded": original, "candidates": []}
    for candidate in candidates:
        packets = candidate.pop("packets", None)
        candidate["geometry_comparison_complete"] = False
        if packets is not None:
            candidate["own_calibration"] = geometry_summary(packets, groups, calibration, config)
            candidate["phone_fixed_calibration"] = geometry_summary(packets, groups, calibration, config, reference)
            candidate["geometry_comparison_complete"] = all(
                candidate[k]["status"] == "ok" and all(p["valid"] == p["selected"]
                    for p in candidate[k]["phases"].values())
                for k in ("own_calibration", "phone_fixed_calibration"))
        result["candidates"].append(candidate)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("report", type=Path)
    for name in ("before", "raised", "after"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--hip-height", type=float, required=True)
    parser.add_argument("--mirrored-input", choices=("yes", "no"), required=True)
    parser.add_argument("--swap-left-right", action="store_true")
    parser.add_argument("--forward-sign", type=int, choices=(-1, 1), required=True)
    parser.add_argument("--yaw", type=float, default=0)
    parser.add_argument("--allow-synthetic", action="store_true", help="test fixtures only; summary keeps synthetic=true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        groups = {name: frame_numbers(getattr(args, name)) for name in ("before", "raised", "after")}
        config = TrackerCalibrationConfig(args.hip_height, args.yaw, args.mirrored_input == "yes", args.forward_sign,
            calibration_seconds=0, minimum_samples=len(groups["before"]), max_sample_gap_ms=5000,
            loss_timeout_ms=5000, swap_left_right=args.swap_left_right)
        result = summarize(args.source, args.report, groups, groups["before"], config, allow_synthetic=args.allow_synthetic)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(result, output, indent=2, ensure_ascii=False, allow_nan=False)
        print(f"ANDROID_REPLAY_VERIFIED synthetic={result['synthetic']}; output={args.output}; no OSC.")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Android replay error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.addaudithook(deny_network)
    raise SystemExit(main())
