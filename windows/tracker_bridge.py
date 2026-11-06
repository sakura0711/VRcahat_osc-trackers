"""Safety gate for live phone poses before local VRChat OSC tracker output."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from console_status import StatusConsole
from tracker_output import ROLES, TrackerOutput, TrackerTransform
from tracker_pose import LANDMARK_NAMES, TrackerCalibrationConfig, TrackerPoseCalibrator


@dataclass(frozen=True)
class TrackerBridgeConfig:
    calibration: TrackerCalibrationConfig
    slots: Mapping[str, int]
    hold_ms: float = 0.0
    max_jump_m: float = 0.5
    max_yaw_jump_deg: float = 90.0

    def __post_init__(self) -> None:
        timeout = self.calibration.loss_timeout_ms
        if not 0 < timeout <= 5_000:
            raise ValueError("tracker loss timeout must be in (0, 5000] ms")
        if not math.isfinite(self.hold_ms) or not 0 <= self.hold_ms <= min(timeout, 250):
            raise ValueError("tracker hold must be in [0, min(loss timeout, 250)] ms")
        if not math.isfinite(self.max_jump_m) or self.max_jump_m <= 0:
            raise ValueError("tracker jump limit must be finite and positive")
        if not math.isfinite(self.max_yaw_jump_deg) or not 0 < self.max_yaw_jump_deg <= 180:
            raise ValueError("tracker yaw jump limit must be in (0, 180] degrees")
        if set(self.slots) != set(ROLES) or len(set(self.slots.values())) != len(ROLES) or any(
            type(slot) is not int or not 1 <= slot <= 8 for slot in self.slots.values()
        ):
            raise ValueError("supply distinct tracker IDs 1..8 for all three roles")


class TrackerBridge:
    """Emit complete fresh batches; never turn invalid frames into new poses."""

    def __init__(self, config: TrackerBridgeConfig, port: int = 9000,
                 output: TrackerOutput | None = None,
                 console: StatusConsole | None = None) -> None:
        self.config = config
        self.controller = TrackerPoseCalibrator(config.calibration)
        self.output = output if output is not None else TrackerOutput(config.slots, port)
        self.console = console if console is not None else StatusConsole()
        self.session: str | None = None
        self.last_batch: dict[str, TrackerTransform] | None = None
        self.last_valid_ns: int | None = None
        self.last_progress_ns: int | None = None
        self.last_progress_started_ns: int | None = None
        self.state = "calibrating"
        self.closed = False

    @property
    def output_ready(self) -> bool:
        return self.state == "tracking" and not self.closed

    def _state(self, state: str, reason: str) -> None:
        if state != self.state:
            previous = self.state
            self.state = state
            if state == "lost" and reason not in ("stopped", "new_session"):
                self.console.emit("lost", f"Tracker lost ({reason}); OSC stopped. Recalibration required.")
            elif state == "calibrating" and previous == "lost":
                self.console.emit("loading", "Tracker calibration restarted. Stand with both feet down and full body visible.")
            elif state == "tracking" and previous in ("calibrating", "lost"):
                self.console.emit("ready", "Tracker calibrated; sending OSC. Confirm reception in VRChat.")

    def status_line(self, now_ns: int) -> tuple[str, str]:
        """Human status; timing is a lower bound, never a promise of calibration."""
        controller = self.controller
        diagnostic = controller.diagnostic
        reason = diagnostic.reason
        landmarks = ",".join(LANDMARK_NAMES.get(index, str(index)) for index in diagnostic.landmarks[:4])
        detail = f"{reason} ({landmarks})" if landmarks else reason
        if self.closed:
            return "error", "Tracker output closed; no further OSC updates."
        if self.state == "tracking":
            return "ready", "Tracker active; OSC sends on valid new frames."
        if self.state == "paused":
            remaining = 0.0 if controller.last_valid_ns is None else max(
                0.0, (self.config.calibration.loss_timeout_ms * 1e6 - (now_ns - controller.last_valid_ns)) / 1e9
            )
            return "wait", f"OSC paused ({detail}); valid frames must resume within {remaining:.1f}s or recalibration starts."
        if self.state == "lost":
            return "lost", "Tracker lost; OSC stopped. A continuous valid standing pose is required."
        if controller.started_ns is not None and reason == "calibrating":
            remaining = max(0.0, controller.config.calibration_seconds - (now_ns - controller.started_ns) / 1e9)
            missing = max(0, controller.config.minimum_samples - len(controller.samples))
            return "loading", (
                f"Standing calibration: {len(controller.samples)} valid frames; "
                f"earliest {remaining:.1f}s to time gate, {missing} more frames needed; OSC blocked."
            )
        return "check", (
            f"Standing calibration blocked ({detail}); need at least "
            f"{controller.config.calibration_seconds:g}s and {controller.config.minimum_samples} valid frames; OSC blocked."
        )

    def _clear(self, reason: str) -> None:
        self.controller.reset()
        self.last_batch = None
        self.last_valid_ns = None
        self.last_progress_ns = None
        self.last_progress_started_ns = None
        self._state("lost", reason)

    def _calibration_progress(self, now_ns: int) -> None:
        started_ns = self.controller.started_ns
        if (self.controller.diagnostic.reason == "calibrating" and started_ns is not None and
                (self.last_progress_started_ns != started_ns or self.last_progress_ns is None or
                 now_ns - self.last_progress_ns >= 1_000_000_000)):
            label, message = self.status_line(now_ns)
            self.console.emit(label, message)
            self.last_progress_ns = now_ns
            self.last_progress_started_ns = started_ns

    def _send(self, transforms: Mapping[str, TrackerTransform], stats: Any) -> None:
        if self.closed:
            return
        try:
            stats.osc_updates += self.output.send(transforms)
        except (OSError, ValueError) as error:
            stats.osc_errors += 1
            self.console.emit("error", f"Tracker OSC send failed: {error}", error=True)
            self._clear("output_error")
            self.output.close()
            self.closed = True

    def _jumped(self, current: Mapping[str, TrackerTransform]) -> bool:
        previous = self.last_batch
        if previous is None:
            return False
        for role in ROLES:
            old, new = previous[role], current[role]
            if math.dist(old.position, new.position) > self.config.max_jump_m:
                return True
            yaw_delta = (new.rotation[1] - old.rotation[1] + 180) % 360 - 180
            if abs(yaw_delta) > self.config.max_yaw_jump_deg:
                return True
        return False

    def on_packet(self, packet: dict[str, Any], now_ns: int, stats: Any) -> None:
        if self.closed:
            return
        if packet["session"] != self.session:
            self.session = packet["session"]
            self._clear("new_session")
            self._state("calibrating", "new_session")
        was_calibrated = self.controller.calibration is not None
        transforms = self.controller.ingest(packet, now_ns)
        if was_calibrated and self.controller.calibration is None:
            self.last_batch = None
            self.last_valid_ns = None
            self._state("lost", "timeout")
        if not transforms:
            if self.controller.calibration is None:
                self._state("calibrating", self.controller.diagnostic.reason)
                self._calibration_progress(now_ns)
            else:
                self._state("paused", self.controller.diagnostic.reason)
            return
        if set(transforms) != set(ROLES):
            self._clear("incomplete_batch")
            return
        if self._jumped(transforms):
            self._clear("jump")
            return
        # Only a complete, confident frame updates the freshness clock.
        self.last_batch = dict(transforms)
        self.last_valid_ns = now_ns
        self._send(transforms, stats)
        if not self.closed:
            self._state("tracking", "valid_frame")

    def tick(self, now_ns: int, stats: Any) -> None:
        if self.closed:
            return
        was_calibrated = self.controller.calibration is not None
        self.controller.tick(now_ns)
        if was_calibrated and self.controller.calibration is None:
            self.last_batch = None
            self.last_valid_ns = None
            self._state("lost", "timeout")
            return
        if self.last_valid_ns is None or self.last_batch is None:
            return
        elapsed_ns = now_ns - self.last_valid_ns
        if elapsed_ns < 0:
            return
        if elapsed_ns > max(self.config.hold_ms, 100.0) * 1_000_000:
            self._state("paused", "hold_expired")
        elif self.config.hold_ms > 0:
            self._send(self.last_batch, stats)

    def close(self, stats: Any) -> None:
        self._clear("stopped")
        if not self.closed:
            self.output.close()
            self.closed = True
