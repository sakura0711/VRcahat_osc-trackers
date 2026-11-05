"""Offline phone-landmark to tracker calibration. This module sends no OSC.

MediaPipe world landmarks are hip-centred metres, not room positions. A neutral
standing pose defines the axes and scale. The caller must supply the measured
standing hip height and verify mirror, forward and yaw choices before enabling
any future VRChat output. Hip translation and airborne motion are unobservable
with this single-camera, hip-centred input.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any

from pose_control import point_confident
from tracker_output import TrackerTransform

Vector3 = tuple[float, float, float]
REQUIRED = (11, 12, 23, 24, 27, 28, 29, 30, 31, 32)


def subtract(a: Vector3, b: Vector3) -> Vector3:
    return tuple(x - y for x, y in zip(a, b))  # type: ignore[return-value]


def midpoint(a: Vector3, b: Vector3) -> Vector3:
    return tuple((x + y) / 2 for x, y in zip(a, b))  # type: ignore[return-value]


def dot(a: Vector3, b: Vector3) -> float:
    return sum(x * y for x, y in zip(a, b))


def cross(a: Vector3, b: Vector3) -> Vector3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(value: Vector3) -> Vector3 | None:
    length = math.sqrt(dot(value, value))
    return tuple(x / length for x in value) if length > 1e-6 else None  # type: ignore[return-value]


@dataclass(frozen=True)
class TrackerCalibrationConfig:
    standing_hip_height_m: float
    neutral_yaw_deg: float
    mirrored_input: bool
    forward_sign: int
    confidence: float = 0.5
    calibration_seconds: float = 3.0
    minimum_samples: int = 5
    max_sample_gap_ms: float = 500.0
    loss_timeout_ms: float = 250.0

    def __post_init__(self) -> None:
        numbers = (self.standing_hip_height_m, self.neutral_yaw_deg, self.confidence,
                   self.calibration_seconds, self.max_sample_gap_ms, self.loss_timeout_ms)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in numbers):
            raise ValueError("calibration settings must be finite numbers")
        if not 0.4 <= self.standing_hip_height_m <= 1.5:
            raise ValueError("standing hip height must be 0.4..1.5 m")
        if not -180 <= self.neutral_yaw_deg <= 180:
            raise ValueError("neutral yaw must be -180..180 degrees")
        if type(self.mirrored_input) is not bool or type(self.forward_sign) is not int or self.forward_sign not in (-1, 1):
            raise ValueError("mirror and forward sign must be explicit")
        if not 0 < self.confidence <= 1 or self.calibration_seconds < 0 or self.max_sample_gap_ms <= 0 or self.loss_timeout_ms <= 0:
            raise ValueError("invalid confidence or timing")
        if type(self.minimum_samples) is not int or self.minimum_samples < 2:
            raise ValueError("minimum_samples must be at least 2")


@dataclass(frozen=True)
class Frame:
    points: dict[int, Vector3]
    hip: Vector3
    right: Vector3
    up: Vector3


@dataclass(frozen=True)
class Calibration:
    right: Vector3
    up: Vector3
    forward: Vector3
    scale: float


class TrackerPoseCalibrator:
    """Returns a complete transform batch only for recent, confident poses.

    Any missing required point suppresses the whole frame. A gap beyond the
    loss timeout invalidates calibration, requiring a new neutral stance.
    Stopping OSC on loss cannot immediately remove VRChat's last tracker pose.
    """

    def __init__(self, config: TrackerCalibrationConfig) -> None:
        self.config = config
        self.reset()

    def reset(self) -> None:
        self.calibration: Calibration | None = None
        self.samples: list[Frame] = []
        self.started_ns: int | None = None
        self.last_valid_ns: int | None = None
        self.last_now_ns: int | None = None

    def _frame(self, packet: dict[str, Any]) -> Frame | None:
        if packet.get("personDetected") is not True:
            return None
        normalized, world = packet.get("landmarks"), packet.get("worldLandmarks")
        if not isinstance(normalized, list) or not isinstance(world, list) or len(normalized) != 33 or len(world) != 33:
            return None
        points: dict[int, Vector3] = {}
        for index in REQUIRED:
            image_point, world_point = normalized[index], world[index]
            if not isinstance(image_point, dict) or not isinstance(world_point, dict):
                return None
            if not point_confident(image_point, self.config.confidence):
                return None
            coords = tuple(world_point.get(axis) for axis in ("x", "y", "z"))
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                   for value in coords):
                return None
            x, y, z = coords
            points[index] = (-x if self.config.mirrored_input else x, y, z)
        hip = midpoint(points[23], points[24])
        right = unit(subtract(points[24], points[23]))
        shoulder = midpoint(points[11], points[12])
        ankle = midpoint(points[27], points[28])
        up = unit(subtract(shoulder, ankle))
        if right is None or up is None or dot(subtract(points[24], points[23]), subtract(points[24], points[23])) < 0.01:
            return None
        if math.sqrt(dot(subtract(shoulder, ankle), subtract(shoulder, ankle))) < 0.3:
            return None
        return Frame(points, hip, right, up)

    def _finish_calibration(self) -> None:
        median = lambda vectors: tuple(statistics.median(v[i] for v in vectors) for i in range(3))
        right = unit(median([frame.right for frame in self.samples]))
        up_raw = median([frame.up for frame in self.samples])
        if right is None:
            return
        up = unit(tuple(up_raw[i] - dot(up_raw, right) * right[i] for i in range(3)))
        if up is None:
            return
        # Reject a turning or leaning calibration window.
        if any(dot(frame.right, right) < 0.966 or dot(frame.up, up) < 0.966 for frame in self.samples):
            return
        forward = unit(cross(right, up))
        if forward is None:
            return
        forward = tuple(self.config.forward_sign * value for value in forward)
        distances = []
        for frame in self.samples:
            ground = min(dot(subtract(frame.points[i], frame.hip), up) for i in (29, 30, 31, 32))
            distances.append(-ground)
        distance = statistics.median(distances)
        if not 0.3 <= distance <= 1.5:
            return
        scale = self.config.standing_hip_height_m / distance
        if not 0.5 <= scale <= 2.0:
            return
        # The forward sign must agree with the toes in the neutral stance.
        # A reversed camera-depth convention must never silently calibrate.
        toe_forward = statistics.median(
            dot(subtract(frame.points[toe], frame.points[heel]), forward)
            for frame in self.samples for heel, toe in ((29, 31), (30, 32))
        )
        if toe_forward < 0.03:
            return
        self.calibration = Calibration(right, up, forward, scale)
        self.samples.clear()

    def tick(self, now_ns: int) -> None:
        if self.last_valid_ns is not None and now_ns - self.last_valid_ns > self.config.loss_timeout_ms * 1e6:
            self.reset()

    def ingest(self, packet: dict[str, Any], now_ns: int) -> dict[str, TrackerTransform]:
        if type(now_ns) is not int or now_ns < 0:
            raise ValueError("now_ns must be a nonnegative monotonic integer")
        if self.last_now_ns is not None and now_ns <= self.last_now_ns:
            return {}
        self.tick(now_ns)
        self.last_now_ns = now_ns
        frame = self._frame(packet)
        if frame is None:
            return {}
        if self.calibration is None:
            if self.last_valid_ns is not None and now_ns - self.last_valid_ns > self.config.max_sample_gap_ms * 1e6:
                self.samples.clear()
                self.started_ns = None
            # A raised foot must not define the initial floor.
            sole_y = [min(dot(subtract(frame.points[index], frame.hip), frame.up) for index in (heel, toe))
                      for heel, toe in ((29, 31), (30, 32))]
            if abs(sole_y[0] - sole_y[1]) > 0.08:
                self.samples.clear()
                self.started_ns = None
                self.last_valid_ns = None
                return {}
            if self.started_ns is None:
                self.started_ns = now_ns
            self.samples.append(frame)
            self.last_valid_ns = now_ns
            if (len(self.samples) >= self.config.minimum_samples and
                    now_ns - self.started_ns >= self.config.calibration_seconds * 1e9):
                self._finish_calibration()
                if self.calibration is None:
                    self.samples.clear()
                    self.started_ns = None
            return {}
        transforms = self._transforms(frame)
        if transforms:
            self.last_valid_ns = now_ns
        return transforms

    def _transforms(self, frame: Frame) -> dict[str, TrackerTransform]:
        calibration = self.calibration
        assert calibration is not None

        def local(point: Vector3) -> Vector3:
            relative = subtract(point, frame.hip)
            return tuple(dot(relative, axis) * calibration.scale for axis in
                         (calibration.right, calibration.up, calibration.forward))  # type: ignore[return-value]

        projected = {index: local(point) for index, point in frame.points.items()}
        ground_y = min(projected[index][1] for index in (29, 30, 31, 32))
        yaw = math.radians(self.config.neutral_yaw_deg)
        cosine, sine = math.cos(yaw), math.sin(yaw)

        def position(point: Vector3) -> Vector3:
            x, y, z = point
            return (cosine * x + sine * z, y - ground_y, -sine * x + cosine * z)

        def heading(direction: Vector3) -> float:
            x, _, z = direction
            return (math.degrees(math.atan2(x, z)) + self.config.neutral_yaw_deg + 180) % 360 - 180

        hip_right = subtract(projected[24], projected[23])
        hip_yaw = heading((-hip_right[2], 0.0, hip_right[0]))
        transforms = {"hip": TrackerTransform(position((0.0, 0.0, 0.0)), (0.0, hip_yaw, 0.0))}
        for role, ankle, heel, toe in (("left_foot", 27, 29, 31), ("right_foot", 28, 30, 32)):
            forward = subtract(projected[toe], projected[heel])
            if math.hypot(forward[0], forward[2]) < 0.03:
                return {}
            transforms[role] = TrackerTransform(position(projected[ankle]), (0.0, heading(forward), 0.0))
        if not 0.2 <= transforms["hip"].position[1] <= 1.5:
            return {}
        if any(abs(axis) > 1.5 or not -0.05 <= transform.position[1] <= 1.5
               for role, transform in transforms.items() if role != "hip"
               for axis in (transform.position[0], transform.position[2])):
            return {}
        return transforms
