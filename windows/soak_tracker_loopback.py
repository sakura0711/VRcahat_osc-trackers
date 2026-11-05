"""Check tracker calibration lifecycles with synthetic UDP on loopback only.

Each 30-second cycle includes standing, both foot lifts, a squat, yaw changes,
low confidence, no person, a packet pause and a new phone session. No OSC output
is constructed, and no phone, Wi-Fi, SteamVR or VRChat behavior is tested.
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import threading
import time
from collections import Counter

from pose_receiver import serve
from tracker_output import TrackerTransform
from tracker_pose import TrackerCalibrationConfig, TrackerPoseCalibrator


def phase_at(seconds: float) -> str:
    for end, phase in ((4, "stand"), (6, "right_lift"), (8, "left_lift"),
                       (10, "squat"), (12, "turn_right"), (13, "occluded"),
                       (14, "no_person"), (19, "stand"), (21, "right_lift"),
                       (22, "pause"), (27, "stand"), (30, "turn_left")):
        if seconds < end:
            return phase
    raise ValueError("cycle time must be 0..<30 seconds")


def synthetic_packet(seq: int, phase: str, session: str) -> dict:
    normalized = [dict(x=0.5, y=0.5, z=0.0, visibility=1.0, presence=1.0) for _ in range(33)]
    world = [dict(x=0.0, y=0.0, z=0.0) for _ in range(33)]
    squat = 0.25 if phase == "squat" else 0.0
    turn = 45 if phase == "turn_right" else -45 if phase == "turn_left" else 0
    radians = math.radians(turn)

    def put(index, x, y, z):
        world[index].update(x=math.cos(radians) * x + math.sin(radians) * z,
                            y=y, z=-math.sin(radians) * x + math.cos(radians) * z)

    for side, indices, raised in ((-1, (11, 23, 27, 29, 31), phase == "left_lift"),
                                  (1, (12, 24, 28, 30, 32), phase == "right_lift")):
        shoulder, hip, ankle, heel, toe = indices
        lift = 0.25 if raised else 0.0
        put(shoulder, side * 0.2, 0.4 - squat, 0.0)
        put(hip, side * 0.13, 0.0, 0.0)
        put(ankle, side * 0.15, -0.82 + squat + lift, 0.0)
        put(heel, side * 0.15, -0.9 + squat + lift, -0.06)
        put(toe, side * 0.15, -0.9 + squat + lift, 0.16)
    if phase == "occluded":
        normalized[31]["visibility"] = 0.1
    detected = phase != "no_person"
    now = time.perf_counter_ns()
    return dict(version=1, session=session, seq=seq, captureMonotonicNs=now,
                analysisStartMonotonicNs=now, sendMonotonicNs=now, inferenceMs=0.0,
                personDetected=detected, landmarks=normalized if detected else [],
                worldLandmarks=world if detected else [], testPhase=phase)


def expected_transforms(phase: str) -> dict[str, TrackerTransform]:
    yaw = 45.0 if phase == "turn_right" else -45.0 if phase == "turn_left" else 0.0
    radians = math.radians(yaw)
    result = {"hip": TrackerTransform((0.0, 0.65 if phase == "squat" else 0.9, 0.0), (0.0, yaw, 0.0))}
    for role, x, raised in (("left_foot", -0.15, phase == "left_lift"),
                             ("right_foot", 0.15, phase == "right_lift")):
        result[role] = TrackerTransform((math.cos(radians) * x, 0.33 if raised else 0.08,
                                        -math.sin(radians) * x), (0.0, yaw, 0.0))
    return result


class ScenarioCheck:
    def __init__(self):
        self.controller = TrackerPoseCalibrator(TrackerCalibrationConfig(0.9, 0.0, False, 1))
        self.session = None
        self.calibrations = 0
        self.losses = 0
        self.samples_peak = 0
        self.phase_frames: Counter[str] = Counter()
        self.transform_frames: Counter[str] = Counter()
        self.errors: Counter[str] = Counter()

    def on_packet(self, packet, now_ns):
        if self.session != packet["session"]:
            self.session = packet["session"]
            self.controller.reset()
        was_ready = self.controller.calibration is not None
        values = self.controller.ingest(packet, now_ns)
        ready = self.controller.calibration is not None
        self.calibrations += int(not was_ready and ready)
        self.losses += int(was_ready and not ready)
        self.samples_peak = max(self.samples_peak, len(self.controller.samples))
        phase = packet["testPhase"]
        self.phase_frames[phase] += 1
        if not values:
            return
        self.transform_frames[phase] += 1
        if phase in ("occluded", "no_person"):
            self.errors["transform_while_invalid"] += 1
            return
        expected = expected_transforms(phase)
        if set(values) != set(expected):
            self.errors["incomplete_batch"] += 1
            return
        for role, transform in values.items():
            for actual, wanted in zip((*transform.position, *transform.rotation),
                                      (*expected[role].position, *expected[role].rotation)):
                if not math.isfinite(actual) or abs(actual - wanted) > 1e-5:
                    self.errors["incorrect_transform"] += 1

    def tick(self, now_ns):
        was_ready = self.controller.calibration is not None
        self.controller.tick(now_ns)
        self.losses += int(was_ready and self.controller.calibration is None)


def run(cycles: int = 2, fps: int = 20) -> dict:
    duration = cycles * 30
    check = ScenarioCheck()
    received = []
    worker_errors = []
    sent = acknowledged = bad_acks = ack_timeouts = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server, \
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        server.bind(("127.0.0.1", 0))
        client.bind(("127.0.0.1", 0))
        client.settimeout(0.5)

        def receive():
            try:
                received.append(serve(server, duration + 0.5, 30, "127.0.0.1", observer=check))
            except Exception as error:
                worker_errors.append(type(error).__name__)

        worker = threading.Thread(target=receive, name="tracker-soak-receiver", daemon=True)
        worker.start()
        started = time.monotonic()
        current_cycle = -1
        sequence = 0
        completed = False
        try:
            for index in range(duration * fps):
                due = started + index / fps
                remaining = due - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                cycle, offset = divmod(index, 30 * fps)
                if cycle != current_cycle:
                    current_cycle, sequence = cycle, 0
                phase = phase_at(offset / fps)
                if phase == "pause":
                    continue
                sequence += 1
                frame = synthetic_packet(sequence, phase, f"synthetic-tracker-{cycle}")
                client.sendto(json.dumps(frame, separators=(",", ":")).encode(), server.getsockname())
                sent += 1
                try:
                    ack = json.loads(client.recvfrom(1024)[0])
                    if (ack.get("type") == "ack" and ack.get("session") == frame["session"]
                            and ack.get("seq") == sequence and ack.get("sendMonotonicNs") == frame["sendMonotonicNs"]):
                        acknowledged += 1
                    else:
                        bad_acks += 1
                except socket.timeout:
                    ack_timeouts += 1
            completed = True
        finally:
            if not completed:
                server.close()
            worker.join(timeout=2)
            if worker.is_alive():
                server.close()
                worker.join(timeout=1)
    stats = received[0] if received else None
    covered = all(check.transform_frames[phase] > 0 for phase in
                  ("stand", "right_lift", "left_lift", "squat", "turn_right", "turn_left"))
    ok = (stats is not None and not worker_errors and not worker.is_alive()
          and sent == cycles * 29 * fps and acknowledged == sent and bad_acks == ack_timeouts == 0
          and stats.accepted == sent and stats.missing == stats.out_of_order == stats.malformed == 0
          and stats.osc_updates == 0 and covered and not check.errors
          and check.calibrations >= cycles * 3 and check.losses >= cycles * 2
          and check.samples_peak <= fps * 4)
    return dict(result="PASS" if ok else "FAIL", kind="synthetic_tracker_loopback_only",
                duration_s=duration, fps=fps, sent=sent, acknowledged=acknowledged,
                bad_acks=bad_acks, ack_timeouts=ack_timeouts, worker_errors=worker_errors,
                calibrations=check.calibrations, tracking_losses=check.losses,
                samples_peak=check.samples_peak, phase_frames=dict(check.phase_frames),
                transform_frames=dict(check.transform_frames), invariant_errors=dict(check.errors),
                receiver=stats.summary(duration + 0.5) if stats else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--fps", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 20 or not 10 <= args.fps <= 60:
        parser.error("cycles must be 1..20 and fps 10..60")
    print("SYNTHETIC TRACKER LOOPBACK: no phone, Wi-Fi or OSC output.", flush=True)
    try:
        result = run(args.cycles, args.fps)
    except KeyboardInterrupt:
        print("TRACKER_SOAK_INTERRUPTED: loopback sockets closed.", flush=True)
        return 130
    print("TRACKER_SOAK_RESULT " + json.dumps(result, separators=(",", ":")), flush=True)
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
