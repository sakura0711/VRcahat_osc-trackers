"""Preview phone-derived tracker positions on the terminal without sending OSC.

Run on a private PC IPv4 while the Android app sends to the same UDP port.
Only derived coordinates and aggregate receiver statistics are printed; neither
images nor raw landmarks are saved. This is a direction/quality diagnostic, not
a VRChat FBT test or proof of absolute HMD alignment.
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import sys
from collections import Counter
from typing import Any

from pose_receiver import private_ipv4, serve
from tracker_pose import HeightDiagnostics, LANDMARK_NAMES, TrackerCalibrationConfig, TrackerPoseCalibrator
from tracker_output import TrackerTransform


def display_transform(transform: TrackerTransform) -> dict[str, Any]:
    return {"position_m": [round(value, 3) for value in transform.position],
            "yaw_deg": round(transform.rotation[1], 1)}


def display_height_diagnostics(value: HeightDiagnostics, now_ns: int) -> dict[str, Any]:
    rounded = lambda values: [round(item, 6) for item in values]
    calibration = value.calibration
    return {
        "at_ns": now_ns,
        "scale": round(calibration.scale, 6),
        "basis": {name: rounded(getattr(calibration, name)) for name in ("right", "up", "forward")},
        "model_ankle_right_minus_left_m": rounded(value.model_ankle_delta_m),
        "vertical_components_m": rounded(value.vertical_components_m),
        "ankle_right_minus_left_y_m": round(sum(value.vertical_components_m), 6),
        "ankle_relative_y_m": dict(zip(("left", "right"), rounded(value.ankle_relative_y_m))),
        "sole_relative_y_m": dict(zip(("left_heel", "left_toe", "right_heel", "right_toe"),
                                      rounded(value.sole_relative_y_m))),
        "floor_shift_m": round(value.floor_shift_m, 6),
        "ankle_output_y_m": dict(zip(("left", "right"),
                                     rounded(y + value.floor_shift_m for y in value.ankle_relative_y_m))),
    }


class TrackerPreview:
    def __init__(self, config: TrackerCalibrationConfig, display_interval_s: float = 0.25,
                 summary_only: bool = False, height_diagnostics: bool = False) -> None:
        self.controller = TrackerPoseCalibrator(config)
        self.session: str | None = None
        self.display_interval_ns = int(display_interval_s * 1e9)
        self.last_display_ns: int | None = None
        self.last_summary_ns: int | None = None
        self.summary_only = summary_only
        self.height_diagnostics = height_diagnostics
        self.frames = 0
        self.pose_frames = 0
        self.transform_frames = 0
        self.sessions = 0
        self.calibrations = 0
        self.tracking_losses = 0
        self.rejections: Counter[str] = Counter()
        self.blocked_landmarks: Counter[str] = Counter()

    def _show(self, label: str, values: dict[str, Any]) -> None:
        print(label + " " + json.dumps(values, separators=(",", ":")), flush=True)

    def summary(self) -> dict[str, Any]:
        return {
            "accepted_frames": self.frames,
            "pose_frames": self.pose_frames,
            "transform_frames": self.transform_frames,
            "transform_frame_pct": round(100 * self.transform_frames / self.frames, 2) if self.frames else None,
            "sessions": self.sessions,
            "calibrations": self.calibrations,
            "tracking_losses": self.tracking_losses,
            "rejection_frames": dict(self.rejections),
            "blocked_landmark_frames": dict(self.blocked_landmarks),
        }

    def _maybe_summary(self, now_ns: int) -> None:
        if self.last_summary_ns is None:
            self.last_summary_ns = now_ns
        elif now_ns - self.last_summary_ns >= 5_000_000_000:
            self._show("PREVIEW_QUALITY", self.summary())
            self.last_summary_ns = now_ns

    def report_final(self) -> None:
        self._show("PREVIEW_FINAL", self.summary())

    def on_packet(self, packet: dict[str, Any], now_ns: int) -> None:
        self.frames += 1
        self.pose_frames += int(packet["personDetected"])
        if packet["session"] != self.session:
            self.session = packet["session"]
            self.sessions += 1
            self.controller.reset()
            self.last_display_ns = None
            print("PREVIEW_SESSION: new phone session; stand still with both feet on the floor.", flush=True)
        was_ready = self.controller.calibration is not None
        transforms = self.controller.ingest(packet, now_ns)
        ready = self.controller.calibration is not None
        if was_ready and not ready:
            self.tracking_losses += 1
            print("PREVIEW_LOST: calibration expired; stand still to recalibrate.", flush=True)
        if not was_ready and ready:
            self.calibrations += 1
            self._show("PREVIEW_CALIBRATED", {"scale": round(self.controller.calibration.scale, 3)})
        diagnostic = self.controller.diagnostic
        if transforms:
            self.transform_frames += 1
        elif diagnostic.reason not in ("calibrating", "calibrated"):
            self.rejections[diagnostic.reason] += 1
            self.blocked_landmarks.update(LANDMARK_NAMES[index] for index in diagnostic.landmarks)
        self._maybe_summary(now_ns)
        if self.summary_only:
            return
        if self.last_display_ns is not None and now_ns - self.last_display_ns < self.display_interval_ns:
            return
        self.last_display_ns = now_ns
        if transforms:
            self._show("PREVIEW_TRACKERS", {role: display_transform(transform)
                                            for role, transform in transforms.items()})
            if self.height_diagnostics and self.controller.height_diagnostics is not None:
                self._show("PREVIEW_HEIGHT_DIAGNOSTICS",
                           display_height_diagnostics(self.controller.height_diagnostics, now_ns))
        else:
            self._show("PREVIEW_WAIT", {"state": "paused" if ready else "calibrating",
                                        "person_detected": packet["personDetected"],
                                        "standing_samples": len(self.controller.samples),
                                        "reason": diagnostic.reason,
                                        "blocked_landmarks": [LANDMARK_NAMES[index] for index in diagnostic.landmarks]})

    def tick(self, now_ns: int) -> None:
        was_ready = self.controller.calibration is not None
        self.controller.tick(now_ns)
        if was_ready and self.controller.calibration is None:
            self.tracking_losses += 1
            print("PREVIEW_LOST: no complete pose within timeout; stand still to recalibrate.", flush=True)
        self._maybe_summary(now_ns)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1", help="specific private PC IPv4 address")
    parser.add_argument("--port", type=int, default=8765, help="phone UDP destination port")
    parser.add_argument("--allow-sender", help="phone's private IPv4 address")
    parser.add_argument("--hip-height", type=float, required=True, help="measured standing floor-to-hip-midpoint metres")
    parser.add_argument("--mirror", choices=("yes", "no"), required=True,
                        help="whether the image sent to MediaPipe was mirrored")
    parser.add_argument("--forward-sign", type=int, choices=(-1, 1), required=True,
                        help="choose the depth sign that makes standing toes point forward")
    parser.add_argument("--swap-left-right", action="store_true",
                        help="swap model body-side labels after checking physical left/right motion")
    parser.add_argument("--yaw", type=float, default=0.0, help="neutral yaw degrees; use zero for initial direction checks")
    parser.add_argument("--duration", type=float, default=60.0, help="maximum preview seconds")
    parser.add_argument("--summary-only", action="store_true",
                        help="show events and quality totals without per-frame coordinates")
    parser.add_argument("--height-diagnostics", action="store_true",
                        help="show model ankle separation, calibration axes and floor-shift decomposition; no OSC")
    args = parser.parse_args(argv)
    if not private_ipv4(args.bind) or args.bind == "0.0.0.0":
        parser.error("--bind must be a specific RFC1918 or loopback IPv4 address")
    if args.allow_sender and not private_ipv4(args.allow_sender):
        parser.error("--allow-sender must be a private IPv4 address")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be 1..65535")
    if not math.isfinite(args.duration) or args.duration <= 0 or args.duration > 3600:
        parser.error("--duration must be finite and 0..3600 seconds")
    try:
        config = TrackerCalibrationConfig(
            standing_hip_height_m=args.hip_height,
            neutral_yaw_deg=args.yaw,
            mirrored_input=args.mirror == "yes",
            forward_sign=args.forward_sign,
            swap_left_right=args.swap_left_right,
        )
    except ValueError as error:
        parser.error(str(error))
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((args.bind, args.port))
            print(f"PREVIEW_LISTENING {args.bind}:{args.port}; no OSC socket is opened.", flush=True)
            preview = TrackerPreview(config, summary_only=args.summary_only,
                                     height_diagnostics=args.height_diagnostics)
            try:
                serve(sock, args.duration, 30.0, args.allow_sender, observer=preview)
            finally:
                preview.report_final()
    except OSError as error:
        print(f"preview error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
