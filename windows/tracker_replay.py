"""Inspect or explicitly play three calibrated poses from a saved image ZIP.

Default: prepare/print only, no socket. OSC mode holds the first pose for FBT
setup until stdin 'play'; then standing -> right_box -> returned, one cycle.
These are repeated stills, not fresh tracking, interpolation or latency tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import queue
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from inspect_pose_pairs import read_pairs
from offline_pose_compare import frame_numbers
from tracker_output import ROLES, TrackerOutput, TrackerTransform, osc_vector
from tracker_pose import TrackerCalibrationConfig, TrackerPoseCalibrator


@dataclass(frozen=True)
class ReplayPose:
    name: str
    source_index: int
    source_frame_id: int
    image_sha256: str
    transforms: Mapping[str, TrackerTransform]


@dataclass(frozen=True)
class ReplayPlan:
    source_sha256: str
    capture_session: str
    config: TrackerCalibrationConfig
    calibration: dict
    calibration_frames: tuple[int, ...]
    rotation_policy: str
    poses: tuple[ReplayPose, ...]

    def summary(self) -> dict:
        return {"format": "vrchat-track-static-replay-plan", "version": 1,
                "source_sha256": self.source_sha256, "capture_session": self.capture_session,
                "config": asdict(self.config), "calibration": self.calibration,
                "calibration_frames": self.calibration_frames, "rotation_policy": self.rotation_policy,
                "height_gain": 1, "interpolation": False, "live_tracking": False,
                "poses": [{"name": p.name, "source_index": p.source_index,
                           "source_frame_id": p.source_frame_id, "image_sha256": p.image_sha256,
                           "transforms": {k: asdict(v) for k, v in p.transforms.items()}} for p in self.poses]}


def validate_batch(batch: Mapping[str, TrackerTransform]) -> None:
    if set(batch) != set(ROLES):
        raise ValueError("replay requires complete hip/left/right batches")
    for slot, role in enumerate(ROLES, 1):
        t = batch[role]
        osc_vector(slot, "position", t.position)
        osc_vector(slot, "rotation", t.rotation)
        x, y, z = t.position
        if abs(x) > 1.5 or abs(z) > 1.5 or not (-0.05 <= y <= 1.5):
            raise ValueError("replay position outside diagnostic bounds")
        if role == "hip" and not 0.2 <= y <= 1.5:
            raise ValueError("replay hip height outside diagnostic bounds")
        if any(abs(a) > 360 for a in t.rotation):
            raise ValueError("replay rotation outside diagnostic bounds")


def prepare(source: Path, calibration_frames: list[int], phase_frames: tuple[int, int, int],
            config: TrackerCalibrationConfig, rotation_policy: str = "standing",
            expected_sha256: str | None = None) -> ReplayPlan:
    if not source.is_file():
        raise ValueError("replay requires an original ZIP file")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256.lower():
        raise ValueError("source ZIP SHA-256 mismatch")
    manifest, frames = read_pairs(source)
    selected = calibration_frames + list(phase_frames)
    if (len(calibration_frames) < 2 or calibration_frames != sorted(set(calibration_frames)) or
            any(type(n) is not int or not 1 <= n <= len(frames) for n in selected) or
            not phase_frames[0] < phase_frames[1] < phase_frames[2] or
            phase_frames[0] not in calibration_frames or max(calibration_frames) >= phase_frames[1]):
        raise ValueError("invalid neutral/calibration/phase frame selection")
    if config.minimum_samples != len(calibration_frames) or rotation_policy not in ("standing", "recorded"):
        raise ValueError("invalid calibration sample count or rotation policy")
    if any(frames[n - 1]["metadata"]["packet"]["mirroredInput"] != config.mirrored_input for n in selected):
        raise ValueError("mirror setting does not match source image metadata")
    controller = TrackerPoseCalibrator(config)
    for n in calibration_frames:
        packet = frames[n - 1]["metadata"]["packet"]
        controller.ingest(packet, packet["resultTimestampMs"] * 1_000_000)
        if controller.calibration is None and (not controller.samples or controller.last_valid_ns is None):
            raise ValueError("neutral calibration rejected: " + controller.diagnostic.reason)
    if controller.calibration is None:
        raise ValueError("neutral calibration failed: " + controller.diagnostic.reason)
    poses = []
    for name, n in zip(("standing", "right_box", "returned"), phase_frames):
        meta = frames[n - 1]["metadata"]
        frame = controller._frame(meta["packet"])
        transforms = controller._transforms(frame) if frame is not None else {}
        if not transforms:
            raise ValueError(f"{name} frame rejected: {controller.diagnostic.reason}")
        if poses and rotation_policy == "standing":
            transforms = {role: TrackerTransform(t.position, poses[0].transforms[role].rotation)
                          for role, t in transforms.items()}
        validate_batch(transforms)
        poses.append(ReplayPose(name, n, meta["frameId"], meta["image"]["sha256"], MappingProxyType(dict(transforms))))
    return ReplayPlan(digest, manifest["captureSession"], config, asdict(controller.calibration),
                      tuple(calibration_frames), rotation_policy, tuple(poses))


def validate_slots(slots: dict[str, int | None]) -> None:
    if (set(slots) != set(ROLES) or any(type(x) is not int or not 1 <= x <= 8 for x in slots.values()) or
            len(set(slots.values())) != 3):
        raise ValueError("OSC requires three explicit, distinct tracker IDs (1..8)")


def play(plan: ReplayPlan, send: Callable, commands: queue.SimpleQueue, *, hz: float = 20,
         pose_seconds: float = 8, max_seconds: float = 180, stop: threading.Event | None = None,
         observer: Callable = lambda name: None, clock: Callable = time.monotonic,
         wait: Callable | None = None) -> dict:
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (hz, pose_seconds, max_seconds)):
        raise ValueError("playback timing must be finite")
    if not 1 <= hz <= 60 or not 1 <= pose_seconds <= 60 or not 1 <= max_seconds <= 600:
        raise ValueError("playback timing outside diagnostic limits")
    if tuple(p.name for p in plan.poses) != ("standing", "right_box", "returned"):
        raise ValueError("invalid replay sequence")
    for pose in plan.poses:
        validate_batch(pose.transforms)
    stop = stop or threading.Event()
    wait = wait or stop.wait
    started = clock()
    deadline = started + max_seconds
    sequence_start = None
    previous_phase = None
    last_send = None
    updates = 0
    reason = "stopped"
    restored = False
    try:
        while True:
            now = clock()
            while not commands.empty():
                command = commands.get()
                if command == "quit":
                    stop.set()
                    break
                if command == "play":
                    sequence_start = now
                elif command == "stand":
                    sequence_start = None
            if stop.is_set():
                reason = "stopped"
                break
            if now >= deadline:
                reason = "timeout"
                break
            if last_send is not None and now - last_send > max(0.5, 4 / hz):
                reason = "stalled"
                break
            phase_index = 0 if sequence_start is None else int((now - sequence_start) / pose_seconds)
            if phase_index >= 3:
                reason = "complete"
                break
            pose = plan.poses[phase_index]
            label = "calibration_standing" if sequence_start is None else pose.name
            if label != previous_phase:
                observer(label)
                previous_phase = label
            if send(pose.transforms) != 6:
                raise RuntimeError("incomplete tracker update")
            updates += 1
            last_send = now
            wait(1 / hz)
    finally:
        # One known neutral batch is best effort; stopping does not immediately
        # remove VRChat's last tracker state. The caller always closes transport.
        try:
            restored = send(plan.poses[0].transforms) == 6
        except OSError:
            restored = False
    return {"reason": reason, "updates": updates, "neutral_restore_sent": restored,
            "osc_datagrams": 6 * (updates + int(restored))}


def read_commands(stream, commands: queue.SimpleQueue) -> None:
    for line in stream:
        value = line.strip().lower()
        if value in ("play", "stand", "quit"):
            commands.put(value)
    commands.put("quit")  # Closed terminal/stdin must not leave a sender running.


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--calibration-frames", required=True)
    parser.add_argument("--stand-frame", required=True, type=int)
    parser.add_argument("--box-frame", required=True, type=int)
    parser.add_argument("--return-frame", required=True, type=int)
    parser.add_argument("--hip-height", required=True, type=float)
    parser.add_argument("--mirror", required=True, choices=("yes", "no"))
    parser.add_argument("--swap-left-right", action="store_true")
    parser.add_argument("--forward-sign", required=True, type=int, choices=(-1, 1))
    parser.add_argument("--yaw", type=float, default=0)
    parser.add_argument("--rotations", choices=("standing", "recorded"), default="standing")
    parser.add_argument("--expect-sha256", help="required for OSC; exact reviewed original ZIP")
    parser.add_argument("--report", type=Path, help="optional new plan JSON; never overwritten")
    parser.add_argument("--osc", action="store_true", help="explicitly enable local tracker output")
    parser.add_argument("--hip-id", type=int)
    parser.add_argument("--left-foot-id", type=int)
    parser.add_argument("--right-foot-id", type=int)
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--hz", type=float, default=20)
    parser.add_argument("--pose-seconds", type=float, default=8)
    parser.add_argument("--max-seconds", type=float, default=180)
    args = parser.parse_args(argv)
    try:
        if (not 1 <= args.port <= 65535 or not all(math.isfinite(x) for x in
                (args.hz, args.pose_seconds, args.max_seconds)) or not 1 <= args.hz <= 60 or
                not 1 <= args.pose_seconds <= 60 or not 1 <= args.max_seconds <= 600):
            raise ValueError("invalid port or playback timing")
        slots = dict(zip(ROLES, (args.hip_id, args.left_foot_id, args.right_foot_id)))
        if args.osc:
            validate_slots(slots)
            if not args.expect_sha256 or len(args.expect_sha256) != 64:
                raise ValueError("OSC requires reviewed source SHA-256")
        samples = frame_numbers(args.calibration_frames)
        config = TrackerCalibrationConfig(args.hip_height, args.yaw, args.mirror == "yes", args.forward_sign,
            calibration_seconds=0, minimum_samples=len(samples), max_sample_gap_ms=5000,
            loss_timeout_ms=5000, swap_left_right=args.swap_left_right)
        plan = prepare(args.source, samples, (args.stand_frame, args.box_frame, args.return_frame),
                       config, args.rotations, args.expect_sha256)
        if args.report:
            with args.report.open("x", encoding="utf-8") as output:
                json.dump(plan.summary(), output, indent=2, ensure_ascii=False, allow_nan=False)
        print("REPLAY_PREPARED " + json.dumps(plan.summary(), ensure_ascii=True, allow_nan=False), flush=True)
        if not args.osc:
            print("INSPECTION_ONLY: no socket or OSC; use explicit --osc and confirmed role IDs to arm.")
            return 0
        commands = queue.SimpleQueue()
        output = TrackerOutput(slots, args.port)
        try:
            threading.Thread(target=read_commands, args=(sys.stdin, commands), daemon=True).start()
            print("OSC_ARMED: standing only. FBT setup first; 'play' starts one cycle, 'stand' resets, 'quit' stops.", flush=True)
            summary = play(plan, output.send, commands, hz=args.hz, pose_seconds=args.pose_seconds,
                           max_seconds=args.max_seconds,
                           observer=lambda name: print("REPLAY_PHASE " + name, flush=True))
            print("REPLAY_STOPPED " + json.dumps(summary), flush=True)
        finally:
            output.close()
            print("Stopped sending. VRChat may retain the last tracker pose; use its OSC/FBT controls if needed.", flush=True)
        return 0
    except KeyboardInterrupt:
        print("Replay interrupted.", flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"replay error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
