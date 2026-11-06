"""Opt-in same-packet landmark recordings and offline verification; no network IO."""

from __future__ import annotations

import argparse
import json
import math
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tracker_pose import LANDMARK_NAMES, SWAPPED_LANDMARKS, TrackerCalibrationConfig, TrackerPoseCalibrator


class TrackerRecording:
    """Write every accepted packet, independent of terminal display throttling.

    Coordinates in packet are unchanged model outputs. Role indices document
    the explicit side mapping; the controller's mirror correction is separate.
    Files are created exclusively and never overwrite a previous measurement.
    """

    def __init__(self, path: str | Path, config: TrackerCalibrationConfig,
                 metadata: dict[str, Any] | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._file = self.path.open("x", encoding="utf-8", buffering=1)
        try:
            self.write({
                "type": "header", "format": "vrchat-track-preview", "version": 1,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "config": asdict(config), "metadata": metadata or {},
                "source_indices": {name: SWAPPED_LANDMARKS.get(index, index)
                                   if config.swap_left_right else index
                                   for index, name in LANDMARK_NAMES.items()},
                "coordinates": {
                    "packet.landmarks": "original image-normalized model coordinates, not metres",
                    "packet.worldLandmarks": "original hip-centred model estimates in metres",
                    "height_diagnostics": "after explicit side mapping, mirror correction and calibration",
                },
                "images_saved": False, "osc_output_enabled": False,
            })
        except BaseException:
            self._file.close()
            raise

    def write(self, value: dict[str, Any]) -> None:
        line = json.dumps(value, separators=(",", ":"), allow_nan=False)
        with self._lock:
            self._file.write(line + "\n")

    def frame(self, packet: dict[str, Any], now_ns: int, controller: TrackerPoseCalibrator,
              transforms: dict[str, Any]) -> None:
        self.write({
            "type": "frame", "at_ns": now_ns, "packet": packet,
            "diagnostic": asdict(controller.diagnostic),
            "transforms": {role: asdict(value) for role, value in transforms.items()},
            "height_diagnostics": asdict(controller.height_diagnostics)
            if controller.height_diagnostics is not None else None,
        })

    def __enter__(self) -> TrackerRecording:
        return self

    def __exit__(self, *args: Any) -> None:
        self._file.close()


def _equivalent(actual: Any, expected: Any) -> bool:
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_equivalent(actual[k], expected[k]) for k in actual)
    if isinstance(actual, (tuple, list)) and isinstance(expected, (tuple, list)):
        return len(actual) == len(expected) and all(_equivalent(a, b) for a, b in zip(actual, expected))
    if type(actual) in (int, float) and type(expected) in (int, float):
        return math.isclose(actual, expected, rel_tol=0, abs_tol=1e-9)
    return actual == expected


def replay_recording(path: str | Path) -> dict[str, int]:
    """Replay frames/ticks without sockets; verify the recorded transformation.

    This checks reproducibility, not whether model coordinates match reality.
    A missing final summary indicates an incomplete capture and is reported.
    """
    counts = {"frames": 0, "transform_frames": 0, "ticks": 0, "summaries": 0}
    session = None
    with Path(path).open(encoding="utf-8") as stream:
        header = json.loads(next(stream))
        if header.get("format") != "vrchat-track-preview" or header.get("version") != 1:
            raise ValueError("unsupported tracker recording")
        controller = TrackerPoseCalibrator(TrackerCalibrationConfig(**header["config"]))
        for line_number, line in enumerate(stream, 2):
            event = json.loads(line)
            if event["type"] == "tick":
                controller.tick(event["at_ns"])
                counts["ticks"] += 1
            elif event["type"] == "frame":
                packet = event["packet"]
                if packet["session"] != session:
                    controller.reset()
                    session = packet["session"]
                transforms = controller.ingest(packet, event["at_ns"])
                actual = {
                    "transforms": {role: asdict(value) for role, value in transforms.items()},
                    "diagnostic": asdict(controller.diagnostic),
                    "height_diagnostics": asdict(controller.height_diagnostics)
                    if controller.height_diagnostics is not None else None,
                }
                if not _equivalent(actual, {key: event[key] for key in actual}):
                    raise ValueError(f"recording replay mismatch at line {line_number}")
                counts["frames"] += 1
                counts["transform_frames"] += bool(transforms)
            elif event["type"] == "summary":
                counts["summaries"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", help="JSONL capture to verify without network access")
    args = parser.parse_args()
    try:
        result = replay_recording(args.recording)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        parser.exit(1, f"replay error: {error}\n")
    print("REPLAY_VERIFIED " + json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
