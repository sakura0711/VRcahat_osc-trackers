"""Convert MediaPipe world landmarks into six calibrated local OSC parameters."""

from __future__ import annotations

import math
import socket
import statistics
import struct
from collections import deque
from dataclasses import dataclass, field
from typing import Any

# Shoulder, elbow, wrist, hip, knee and ankle indices, using MediaPipe labels.
JOINTS = {
    "Puppet/LeftArmRaise": (11, 13, 23),
    "Puppet/RightArmRaise": (12, 14, 24),
    "Puppet/LeftElbowFlex": (11, 13, 15),
    "Puppet/RightElbowFlex": (12, 14, 16),
    "Puppet/LeftKneeFlex": (23, 25, 27),
    "Puppet/RightKneeFlex": (24, 26, 28),
}
PARAMETERS = tuple(JOINTS)
DEFAULT_CONFIDENCE = 0.5
CALIBRATION_MAX_GAP_NS = 1_000_000_000
# Calibration uses a T-pose (arm value 0). When tracking is unavailable,
# lowered arms are a more natural idle than returning to the T-pose.
IDLE_VALUES = {name: -1.0 if name.endswith("ArmRaise") else 0.0 for name in PARAMETERS}


def point_confident(point: dict[str, Any], threshold: float) -> bool:
    available = [point.get(key) for key in ("visibility", "presence") if point.get(key) is not None]
    return bool(available) and min(available) >= threshold


def angle(a: dict[str, float], origin: dict[str, float], b: dict[str, float]) -> float | None:
    u = tuple(a[axis] - origin[axis] for axis in ("x", "y", "z"))
    v = tuple(b[axis] - origin[axis] for axis in ("x", "y", "z"))
    length = math.sqrt(sum(x * x for x in u) * sum(x * x for x in v))
    if length < 1e-9:
        return None
    cosine = max(-1.0, min(1.0, sum(x * y for x, y in zip(u, v)) / length))
    return math.degrees(math.acos(cosine))


def joint_angles(packet: dict[str, Any], threshold: float) -> dict[str, float]:
    if not packet["personDetected"]:
        return {}
    normalized, world = packet["landmarks"], packet["worldLandmarks"]
    output: dict[str, float] = {}
    for name, indices in JOINTS.items():
        if not all(point_confident(normalized[i], threshold) for i in indices):
            continue
        a, b, c = (world[i] for i in indices)
        # Arm raise compares shoulder->elbow with shoulder->hip. Flexion is
        # 180 degrees minus the interior angle at the elbow or knee.
        value = angle(b, a, c) if name.endswith("ArmRaise") else angle(a, b, c)
        if value is not None:
            output[name] = value if name.endswith("ArmRaise") else 180.0 - value
    return output


@dataclass
class PoseController:
    calibration_seconds: float = 3.0
    confidence: float = DEFAULT_CONFIDENCE
    smoothing_ms: float = 35.0
    hold_ms: float = 250.0
    minimum_calibration_samples: int = 5
    started_ns: int | None = None
    calibration: dict[str, deque[tuple[int, float]]] = field(
        default_factory=lambda: {name: deque(maxlen=600) for name in PARAMETERS}
    )
    baseline: dict[str, float] | None = None
    filtered: dict[str, float] = field(default_factory=dict)
    last_seen_ns: dict[str, int] = field(default_factory=dict)
    last_filter_ns: dict[str, int] = field(default_factory=dict)

    def reset(self) -> None:
        self.started_ns = None
        self.calibration = {name: deque(maxlen=600) for name in PARAMETERS}
        self.baseline = None
        self.filtered.clear()
        self.last_seen_ns.clear()
        self.last_filter_ns.clear()

    def ingest(self, packet: dict[str, Any], now_ns: int) -> dict[str, float]:
        angles = joint_angles(packet, self.confidence)
        if self.baseline is None:
            # Old observations cannot stand in for a joint that is now
            # occluded. Keep a small minimum window for short test runs.
            cutoff_ns = now_ns - int(max(self.calibration_seconds, 1.0) * 1e9)
            for samples in self.calibration.values():
                while samples and samples[0][0] < cutoff_ns:
                    samples.popleft()
            if self.started_ns is not None and any(
                not samples or now_ns - samples[-1][0] > CALIBRATION_MAX_GAP_NS
                for samples in self.calibration.values()
            ):
                # This also catches an interruption with no incoming packets.
                self.started_ns = None
            for name, value in angles.items():
                self.calibration[name].append((now_ns, value))
            all_recent = all(
                samples and now_ns - samples[-1][0] <= CALIBRATION_MAX_GAP_NS
                for samples in self.calibration.values()
            )
            if all_recent:
                if self.started_ns is None:
                    self.started_ns = now_ns
                elapsed = (now_ns - self.started_ns) / 1e9
                if elapsed >= self.calibration_seconds and all(
                    len(values) >= self.minimum_calibration_samples for values in self.calibration.values()
                ):
                    self.baseline = {
                        name: statistics.median(value for _, value in values)
                        for name, values in self.calibration.items()
                    }
                    self.filtered = {name: 0.0 for name in PARAMETERS}
                    self.last_seen_ns = {name: now_ns for name in PARAMETERS}
                    self.last_filter_ns = {name: now_ns for name in PARAMETERS}
                    return dict(self.filtered)
            return {}

        result = self.tick(now_ns)
        for name, value in angles.items():
            # A 90-degree deviation from the calibrated rest pose maps to 1.
            target = max(-1.0, min(1.0, (value - self.baseline[name]) / 90.0))
            previous_ns = self.last_filter_ns.get(name)
            dt_ms = max(0.0, (now_ns - previous_ns) / 1e6) if previous_ns is not None else 0.0
            alpha = 1.0 if self.smoothing_ms <= 0 or previous_ns is None else 1.0 - math.exp(-dt_ms / self.smoothing_ms)
            filtered = self.filtered.get(name, 0.0) + alpha * (target - self.filtered.get(name, 0.0))
            self.filtered[name] = filtered
            self.last_seen_ns[name] = now_ns
            self.last_filter_ns[name] = now_ns
            result[name] = filtered
        return result

    def tick(self, now_ns: int) -> dict[str, float]:
        if self.baseline is None:
            return {}
        expired: dict[str, float] = {}
        for name, last_ns in list(self.last_seen_ns.items()):
            if now_ns - last_ns >= self.hold_ms * 1e6:
                # A lost joint returns to the idle pose once after the hold period.
                self.filtered[name] = IDLE_VALUES[name]
                self.last_filter_ns.pop(name, None)
                self.last_seen_ns.pop(name, None)
                expired[name] = IDLE_VALUES[name]
        return expired


def osc_string(value: str) -> bytes:
    encoded = value.encode("utf-8") + b"\x00"
    return encoded + b"\x00" * (-len(encoded) % 4)


def osc_float(parameter: str, value: float) -> bytes:
    if parameter not in JOINTS or not math.isfinite(value) or not -1.0 <= value <= 1.0:
        raise ValueError("invalid OSC parameter or value")
    return osc_string("/avatar/parameters/" + parameter) + osc_string(",f") + struct.pack(">f", value)


class OscOutput:
    def __init__(self, port: int = 9000) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.address = ("127.0.0.1", port)

    def send(self, values: dict[str, float]) -> None:
        for name, value in values.items():
            self.socket.sendto(osc_float(name, value), self.address)

    def close(self) -> None:
        self.socket.close()
