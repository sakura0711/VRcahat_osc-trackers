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
    hold_ms: float = 8000.0
    max_jump_m: float = 0.5
    max_yaw_jump_deg: float = 90.0
    transition_ms: float = 300.0

    def __post_init__(self) -> None:
        timeout = self.calibration.loss_timeout_ms
        if not 0 < timeout <= 5_000:
            raise ValueError("tracker loss timeout must be in (0, 5000] ms")
        if (not math.isfinite(self.hold_ms) or not 0 <= self.hold_ms <= 8000
                or 0 < self.hold_ms < timeout):
            raise ValueError("tracker hold must be zero or between loss timeout and 8000 ms")
        if not math.isfinite(self.transition_ms) or not 0 < self.transition_ms <= 1000:
            raise ValueError("tracker recovery transition must be in (0, 1000] ms")
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
        self.controller = TrackerPoseCalibrator(config.calibration, retain_calibration_on_loss=True)
        self.output = output if output is not None else TrackerOutput(config.slots, port)
        self.console = console if console is not None else StatusConsole()
        self.session: str | None = None
        self.last_batch: dict[str, TrackerTransform] | None = None
        self.last_valid_ns: int | None = None
        self.last_sent: dict[str, TrackerTransform] | None = None
        self.last_send_ns: int | None = None
        self.interrupted = False
        self.expired = False
        self.transition_start_ns: int | None = None
        self.transition_from: dict[str, TrackerTransform] | None = None
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
            if state == "lost" and reason not in ("stopped", "new_session", "hold_expired"):
                self.console.emit("lost", f"Tracker lost ({reason}); OSC stopped. Recalibration required.")
            elif state == "lost" and reason == "hold_expired":
                self.console.emit("lost", "Freeze expired; OSC stopped. Press R or restart to recalibrate.")
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
            return "wait", f"Tracker interrupted ({detail}); holding last calibrated pose within freeze limit."
        if self.state == "lost":
            if self.expired:
                return "lost", "Freeze expired; OSC stopped. Press R or restart to recalibrate."
            return "lost", "Tracker lost; OSC stopped. A continuous valid standing pose is required."
        if self.state == "frozen":
            return "wait", "Tracking lost; holding last calibrated pose. Press R to recalibrate."
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
        self.last_sent = None
        self.last_send_ns = None
        self.interrupted = False
        self.expired = False
        self.transition_start_ns = None
        self.transition_from = None
        self.last_progress_ns = None
        self.last_progress_started_ns = None
        self._state("lost", reason)

    def recalibrate(self) -> None:
        """Explicitly discard the old calibration and any frozen output."""
        if not self.closed:
            self._clear("manual_recalibration")
            self._state("calibrating", "manual_recalibration")

    def _calibration_progress(self, now_ns: int) -> None:
        started_ns = self.controller.started_ns
        if (self.controller.diagnostic.reason == "calibrating" and started_ns is not None and
                (self.last_progress_started_ns != started_ns or self.last_progress_ns is None or
                 now_ns - self.last_progress_ns >= 1_000_000_000)):
            label, message = self.status_line(now_ns)
            self.console.emit(label, message)
            self.last_progress_ns = now_ns
            self.last_progress_started_ns = started_ns

    def _send(self, transforms: Mapping[str, TrackerTransform], stats: Any, now_ns: int) -> None:
        if self.closed:
            return
        try:
            stats.osc_updates += self.output.send(transforms)
            self.last_sent = dict(transforms)
            self.last_send_ns = now_ns
        except (OSError, ValueError) as error:
            stats.osc_errors += 1
            self.console.emit("error", f"Tracker OSC send failed: {error}", error=True)
            self._clear("output_error")
            self.output.close()
            self.closed = True

    def _jumped(self, current: Mapping[str, TrackerTransform],
                previous: Mapping[str, TrackerTransform] | None = None) -> bool:
        if previous is None:
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
        if self.expired:
            return
        if self.last_valid_ns is not None:
            age = now_ns - self.last_valid_ns
            if age < 0:
                return
            if age > max(self.config.hold_ms, self.config.calibration.loss_timeout_ms) * 1_000_000:
                self.expired = True
                self._state("lost", "hold_expired")
                return
            if age > self.config.calibration.loss_timeout_ms * 1_000_000:
                self.interrupted = True
        transforms = self.controller.ingest(packet, now_ns)
        if not transforms:
            if self.controller.calibration is None:
                self._state("calibrating", self.controller.diagnostic.reason)
                self._calibration_progress(now_ns)
            else:
                self.interrupted = True
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
        if self.interrupted and self.last_sent is not None:
            self.transition_from = dict(self.last_sent)
            self.transition_start_ns = now_ns
        self.interrupted = False
        outgoing = transforms
        if self.transition_start_ns is not None and self.transition_from is not None:
            fraction = min(1.0, (now_ns - self.transition_start_ns) / (self.config.transition_ms * 1_000_000))
            outgoing = {}
            for role in ROLES:
                old, new = self.transition_from[role], transforms[role]
                position = tuple(a + fraction * (b - a) for a, b in zip(old.position, new.position))
                rotation = tuple(a + fraction * ((b - a + 180) % 360 - 180)
                                 for a, b in zip(old.rotation, new.rotation))
                outgoing[role] = TrackerTransform(position, rotation)
            if fraction >= 1.0:
                self.transition_start_ns = None
                self.transition_from = None
        if self.last_sent is not None and self._jumped(outgoing, self.last_sent):
            self._clear("output_jump")
            return
        self._send(outgoing, stats, now_ns)
        if not self.closed:
            self._state("tracking", "valid_frame")

    def tick(self, now_ns: int, stats: Any) -> None:
        if self.closed:
            return
        self.controller.tick(now_ns)
        if self.expired or self.last_valid_ns is None or self.last_sent is None:
            return
        elapsed_ns = now_ns - self.last_valid_ns
        if elapsed_ns < 0:
            return
        if elapsed_ns > max(self.config.hold_ms, self.config.calibration.loss_timeout_ms) * 1_000_000:
            self.expired = True
            self._state("lost", "hold_expired")
        elif elapsed_ns > self.config.calibration.loss_timeout_ms * 1_000_000:
            self.interrupted = True
            self._state("frozen", "timeout")
        if (not self.expired and self.interrupted and self.config.hold_ms > 0 and elapsed_ns >= 50_000_000
                and self.last_send_ns is not None and now_ns - self.last_send_ns >= 50_000_000):
            self._send(self.last_sent, stats, now_ns)

    def close(self, stats: Any) -> None:
        self._clear("stopped")
        if not self.closed:
            self.output.close()
            self.closed = True
