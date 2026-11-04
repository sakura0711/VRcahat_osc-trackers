"""Private-LAN UDP pose receiver for the VRChat single-phone MVP.

Run with --bind set to a specific private IPv4 address on this PC.
Only aggregate metrics are printed; landmark coordinates are not logged or saved.
"""

from __future__ import annotations

import argparse
import errno
import ipaddress
import json
import math
import socket
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from pose_control import DEFAULT_CONFIDENCE, IDLE_VALUES, JOINTS, OscOutput, PARAMETERS, PoseController, point_confident

VERSION = 1
LANDMARK_COUNT = 33
MAX_PACKET_BYTES = 16_384
MAX_SESSION_LENGTH = 80
STAT_WINDOW = 10_000
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(block)
    for block in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")
)


def private_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and any(
        address in network for network in PRIVATE_NETWORKS
    )


def finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite number: {value}")


def validate_packet(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_PACKET_BYTES:
        raise ValueError("invalid datagram size")
    try:
        packet = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("invalid JSON") from error
    if not isinstance(packet, dict) or type(packet.get("version")) is not int:
        raise ValueError("invalid version")
    if packet["version"] != VERSION:
        raise ValueError("unsupported version")
    session = packet.get("session")
    if not isinstance(session, str) or not (1 <= len(session) <= MAX_SESSION_LENGTH):
        raise ValueError("invalid session")
    if type(packet.get("seq")) is not int or packet["seq"] < 1:
        raise ValueError("invalid seq")
    for key in ("captureMonotonicNs", "analysisStartMonotonicNs", "sendMonotonicNs"):
        if type(packet.get(key)) is not int or packet[key] < 0:
            raise ValueError(f"invalid {key}")
    if not finite_number(packet.get("inferenceMs")) or packet["inferenceMs"] < 0:
        raise ValueError("invalid inferenceMs")
    if type(packet.get("personDetected")) is not bool:
        raise ValueError("invalid personDetected")
    expected = LANDMARK_COUNT if packet["personDetected"] else 0
    for field_name in ("landmarks", "worldLandmarks"):
        landmarks = packet.get(field_name)
        if not isinstance(landmarks, list) or len(landmarks) != expected:
            raise ValueError(f"invalid {field_name} count")
        for landmark in landmarks:
            if not isinstance(landmark, dict):
                raise ValueError("invalid landmark")
            if not all(finite_number(landmark.get(axis)) for axis in ("x", "y", "z")):
                raise ValueError("invalid landmark coordinate")
            for key in ("visibility", "presence"):
                confidence = landmark.get(key)
                if confidence is not None and (
                    not finite_number(confidence) or not 0.0 <= confidence <= 1.0
                ):
                    raise ValueError("invalid landmark confidence")
    return packet


def percentile(values: deque[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


@dataclass
class ReceiverStats:
    received: int = 0
    accepted: int = 0
    malformed: int = 0
    oversized: int = 0
    udp_resets: int = 0
    unauthorized: int = 0
    ack_errors: int = 0
    out_of_order: int = 0
    missing: int = 0
    pose_frames: int = 0
    no_pose_frames: int = 0
    sessions: int = 0
    peer: str | None = None
    current_session: str | None = None
    last_seq: int | None = None
    retired_sessions: deque[str] = field(default_factory=lambda: deque(maxlen=32))
    first_arrival_ns: int | None = None
    last_arrival_ns: int | None = None
    last_interval_ms: float | None = None
    last_pose: dict[str, Any] | None = None
    intervals_ms: deque[float] = field(default_factory=lambda: deque(maxlen=STAT_WINDOW))
    jitter_ms: deque[float] = field(default_factory=lambda: deque(maxlen=STAT_WINDOW))
    processing_ms: deque[float] = field(default_factory=lambda: deque(maxlen=STAT_WINDOW))
    phone_processing_ms: deque[float] = field(default_factory=lambda: deque(maxlen=STAT_WINDOW))
    pose_to_osc_ms: deque[float] = field(default_factory=lambda: deque(maxlen=STAT_WINDOW))
    packet_bytes: deque[float] = field(default_factory=lambda: deque(maxlen=STAT_WINDOW))
    joint_confident_frames: dict[str, int] = field(default_factory=lambda: dict.fromkeys(PARAMETERS, 0))
    osc_updates: int = 0
    osc_errors: int = 0

    def observe(self, packet: dict[str, Any], peer: str, arrival_ns: int, size: int) -> bool:
        # A run tracks one sender IP. A new session from that sender may restart seq.
        if self.peer is None:
            self.peer = peer
        if self.peer != peer:
            self.unauthorized += 1
            return False
        if packet["session"] != self.current_session:
            if packet["session"] in self.retired_sessions:
                self.out_of_order += 1
                return False
            if self.current_session is not None:
                self.retired_sessions.append(self.current_session)
            self.current_session = packet["session"]
            self.last_seq = None
            self.last_arrival_ns = None
            self.last_interval_ms = None
            self.last_pose = None
            self.sessions += 1
        seq = packet["seq"]
        if self.last_seq is not None:
            if seq <= self.last_seq:
                self.out_of_order += 1
                return False
            self.missing += max(0, seq - self.last_seq - 1)
        if self.last_arrival_ns is not None:
            interval = (arrival_ns - self.last_arrival_ns) / 1_000_000.0
            self.intervals_ms.append(interval)
            if self.last_interval_ms is not None:
                self.jitter_ms.append(abs(interval - self.last_interval_ms))
            self.last_interval_ms = interval
        self.last_arrival_ns = arrival_ns
        if self.first_arrival_ns is None:
            self.first_arrival_ns = arrival_ns
        self.last_seq = seq
        self.accepted += 1
        self.packet_bytes.append(float(size))
        if packet["personDetected"]:
            self.pose_frames += 1
            self.last_pose = packet
            self.phone_processing_ms.append(float(packet["inferenceMs"]))
            landmarks = packet["landmarks"]
            for name, indices in JOINTS.items():
                if all(point_confident(landmarks[index], DEFAULT_CONFIDENCE) for index in indices):
                    self.joint_confident_frames[name] += 1
        else:
            self.no_pose_frames += 1
            self.last_pose = None
        return True

    def summary(self, elapsed_seconds: float) -> dict[str, Any]:
        denominator = self.accepted + self.missing
        arrival_span_ns = (self.last_arrival_ns or 0) - (self.first_arrival_ns or 0)
        arrival_fps = (self.accepted - 1) * 1e9 / arrival_span_ns if arrival_span_ns > 0 else None
        return {
            "elapsed_s": round(elapsed_seconds, 2),
            "received": self.received,
            "accepted": self.accepted,
            "pose_frames": self.pose_frames,
            "no_pose_frames": self.no_pose_frames,
            "pose_frame_pct": round(100.0 * self.pose_frames / self.accepted, 2) if self.accepted else None,
            "schema_errors": self.malformed,
            "oversized": self.oversized,
            "udp_resets": self.udp_resets,
            "unauthorized": self.unauthorized,
            "ack_errors": self.ack_errors,
            "out_of_order": self.out_of_order,
            "sequence_gaps": self.missing,
            "estimated_gap_pct": round(100.0 * self.missing / denominator, 3) if denominator else None,
            "arrival_fps": round(arrival_fps, 2) if arrival_fps is not None else None,
            "pose_arrival_fps": round(arrival_fps * self.pose_frames / self.accepted, 2)
            if arrival_fps is not None and self.accepted else None,
            "interval_p50_ms": percentile(self.intervals_ms, 0.50),
            "interval_p95_ms": percentile(self.intervals_ms, 0.95),
            "interval_jitter_p95_ms": percentile(self.jitter_ms, 0.95),
            "receiver_p50_ms": percentile(self.processing_ms, 0.50),
            "receiver_p95_ms": percentile(self.processing_ms, 0.95),
            "phone_processing_p50_ms": percentile(self.phone_processing_ms, 0.50),
            "phone_processing_p95_ms": percentile(self.phone_processing_ms, 0.95),
            "pose_to_osc_p50_ms": percentile(self.pose_to_osc_ms, 0.50),
            "pose_to_osc_p95_ms": percentile(self.pose_to_osc_ms, 0.95),
            "packet_p95_bytes": percentile(self.packet_bytes, 0.95),
            "sessions": self.sessions,
            "osc_updates": self.osc_updates,
            "osc_errors": self.osc_errors,
            "joint_confident_pct": {
                name: round(100.0 * count / self.pose_frames, 2) if self.pose_frames else None
                for name, count in self.joint_confident_frames.items()
            },
        }


class PoseBridge:
    def __init__(self, port: int, calibration_seconds: float, smoothing_ms: float, hold_ms: float):
        self.controller = PoseController(calibration_seconds=calibration_seconds, smoothing_ms=smoothing_ms, hold_ms=hold_ms)
        self.output = OscOutput(port)
        self.session: str | None = None
        self.last_progress_ns = 0

    def send(self, values: dict[str, float], stats: ReceiverStats) -> None:
        if not values:
            return
        try:
            self.output.send(values)
            stats.osc_updates += len(values)
        except OSError as error:
            stats.osc_errors += 1
            print(f"OSC error: {error}", file=sys.stderr, flush=True)

    def on_packet(self, packet: dict[str, Any], now_ns: int, stats: ReceiverStats) -> None:
        if packet["session"] != self.session:
            self.send(dict(IDLE_VALUES), stats)
            self.session = packet["session"]
            self.controller.reset()
            self.last_progress_ns = 0
            print("CALIBRATION: hold a neutral T-pose until all six joints are ready.", flush=True)
        was_calibrated = self.controller.baseline is not None
        values = self.controller.ingest(packet, now_ns)
        if not was_calibrated and self.controller.baseline is not None:
            print("CALIBRATION: complete; sending six avatar parameters to local VRChat.", flush=True)
        elif self.controller.baseline is None and now_ns - self.last_progress_ns >= 2_000_000_000:
            counts = {name: len(self.controller.calibration[name]) for name in PARAMETERS}
            print("CALIBRATION samples=" + json.dumps(counts, separators=(",", ":")), flush=True)
            self.last_progress_ns = now_ns
        self.send(values, stats)

    def tick(self, now_ns: int, stats: ReceiverStats) -> None:
        self.send(self.controller.tick(now_ns), stats)

    def close(self, stats: ReceiverStats) -> None:
        self.send(dict(IDLE_VALUES), stats)
        self.output.close()


def serve(
    sock: socket.socket,
    duration: float | None,
    report_interval: float,
    allowed_sender: str | None = None,
    bridge: PoseBridge | None = None,
) -> ReceiverStats:
    stats = ReceiverStats()
    started = time.monotonic()
    next_report = started + report_interval
    sock.settimeout(0.05)
    try:
        while duration is None or time.monotonic() - started < duration:
            try:
                data, address = sock.recvfrom(MAX_PACKET_BYTES + 1)
            except socket.timeout:
                data = None
            except ConnectionResetError:
                # Windows reports an ICMP port-unreachable for an earlier ACK
                # on the next receive; it is not a received pose packet.
                stats.udp_resets += 1
                data = None
            except OSError as error:
                if error.errno != errno.EMSGSIZE and getattr(error, "winerror", None) != 10040:
                    raise
                # Windows discards an overlong datagram and raises WSAEMSGSIZE.
                # Other platforms may return a truncated MAX_PACKET_BYTES+1 buffer.
                stats.received += 1
                stats.oversized += 1
                data = None
            if data is not None:
                # perf_counter_ns uses QueryPerformanceCounter on Windows. The
                # Windows monotonic clock may have millisecond-scale resolution.
                arrival_ns = time.perf_counter_ns()
                stats.received += 1
                if not private_ipv4(address[0]) or (allowed_sender and address[0] != allowed_sender):
                    stats.unauthorized += 1
                elif len(data) > MAX_PACKET_BYTES:
                    stats.oversized += 1
                else:
                    try:
                        packet = validate_packet(data)
                    except ValueError:
                        stats.malformed += 1
                    else:
                        if stats.observe(packet, address[0], arrival_ns, len(data)):
                            ack = json.dumps(
                                {
                                    "version": VERSION,
                                    "type": "ack",
                                    "session": packet["session"],
                                    "seq": packet["seq"],
                                    "sendMonotonicNs": packet["sendMonotonicNs"],
                                },
                                separators=(",", ":"),
                            ).encode("utf-8")
                            try:
                                sock.sendto(ack, address)
                            except OSError:
                                stats.ack_errors += 1
                            else:
                                stats.processing_ms.append((time.perf_counter_ns() - arrival_ns) / 1_000_000.0)
                            if bridge is not None:
                                previous_updates = stats.osc_updates
                                bridge.on_packet(packet, time.perf_counter_ns(), stats)
                                if (packet["personDetected"] and bridge.controller.baseline is not None
                                        and stats.osc_updates > previous_updates):
                                    stats.pose_to_osc_ms.append((time.perf_counter_ns() - arrival_ns) / 1_000_000.0)
            now = time.monotonic()
            if bridge is not None:
                bridge.tick(time.perf_counter_ns(), stats)
            if now >= next_report:
                print("STATUS " + json.dumps(stats.summary(now - started), separators=(",", ":")), flush=True)
                next_report = now + report_interval
    except KeyboardInterrupt:
        pass
    finally:
        if bridge is not None:
            bridge.close(stats)
    print("FINAL " + json.dumps(stats.summary(time.monotonic() - started), separators=(",", ":")), flush=True)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1", help="specific private IPv4 address, default 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-sender", help="optional private IPv4 address of the phone")
    parser.add_argument("--duration", type=float, help="stop after this many seconds")
    parser.add_argument("--report-interval", type=float, default=5.0)
    parser.add_argument("--osc", action="store_true", help="send calibrated parameters to local VRChat")
    parser.add_argument("--osc-port", type=int, default=9000, help="local VRChat OSC input port")
    parser.add_argument("--calibration-seconds", type=float, default=3.0)
    parser.add_argument("--smoothing-ms", type=float, default=35.0)
    parser.add_argument("--hold-ms", type=float, default=250.0)
    args = parser.parse_args()
    if not private_ipv4(args.bind):
        parser.error("--bind must be a specific RFC1918 or loopback IPv4 address; 0.0.0.0 is not allowed")
    if args.allow_sender and not private_ipv4(args.allow_sender):
        parser.error("--allow-sender must be a private IPv4 address")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        parser.error("--duration must be finite and positive")
    if not math.isfinite(args.report_interval) or args.report_interval <= 0:
        parser.error("--report-interval must be finite and positive")
    if not 1 <= args.osc_port <= 65535:
        parser.error("--osc-port must be between 1 and 65535")
    if any(not math.isfinite(value) or value < 0 for value in
           (args.calibration_seconds, args.smoothing_ms, args.hold_ms)):
        parser.error("calibration, smoothing, and hold settings must be finite and nonnegative")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((args.bind, args.port))
            print(f"LISTENING {args.bind}:{args.port} (UDP, private network only)", flush=True)
            bridge = PoseBridge(args.osc_port, args.calibration_seconds, args.smoothing_ms, args.hold_ms) if args.osc else None
            if bridge is not None:
                print(f"OSC enabled: 127.0.0.1:{args.osc_port}; sending does not confirm VRChat reception.", flush=True)
            serve(sock, args.duration, args.report_interval, args.allow_sender, bridge)
    except OSError as error:
        print(f"receiver error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
