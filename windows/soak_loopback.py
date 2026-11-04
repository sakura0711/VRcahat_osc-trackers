"""Exercise the receiver with synthetic poses over loopback, not a phone or VRChat."""

from __future__ import annotations

import argparse
import json
import math
import socket
import struct
import threading
import time
import uuid

from pose_control import PARAMETERS
from pose_receiver import PoseBridge, ReceiverStats, serve


def synthetic_pose(seq: int, elapsed: float, session: str) -> dict:
    """Generate 33-point test data with a T-pose, then varying joints."""
    visible = {"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 1.0, "presence": 1.0}
    landmarks = [visible.copy() for _ in range(33)]
    world = [{"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 1.0, "presence": 1.0} for _ in range(33)]

    def put(index: int, xyz: tuple[float, float, float]) -> None:
        world[index].update(zip(("x", "y", "z"), xyz))

    moving = elapsed >= 3.5
    for side, shoulder, elbow, wrist, hip, knee, ankle in (
        (-1.0, 11, 13, 15, 23, 25, 27),
        (1.0, 12, 14, 16, 24, 26, 28),
    ):
        phase = elapsed + (0.0 if side < 0 else 0.7)
        raise_angle = 0.6 * math.sin(phase) if moving else 0.0
        elbow_flex = 0.45 * (1.0 + math.sin(phase * 0.7)) if moving else 0.0
        knee_flex = 0.45 * (1.0 + math.sin(phase * 0.8)) if moving else 0.0
        sx = side * 0.2
        upper = (side * 0.4 * math.cos(raise_angle), 0.4 * math.sin(raise_angle))
        forearm_angle = raise_angle - elbow_flex
        put(shoulder, (sx, 1.0, 0.0))
        put(elbow, (sx + upper[0], 1.0 + upper[1], 0.0))
        put(wrist, (sx + upper[0] + side * 0.4 * math.cos(forearm_angle),
                    1.0 + upper[1] + 0.4 * math.sin(forearm_angle), 0.0))
        put(hip, (sx, 0.0, 0.0))
        put(knee, (sx, -0.5, 0.0))
        put(ankle, (sx, -0.5 - 0.5 * math.cos(knee_flex), 0.5 * math.sin(knee_flex)))

    now = time.monotonic_ns()
    return {
        "version": 1, "session": session, "seq": seq,
        "captureMonotonicNs": now, "analysisStartMonotonicNs": now,
        "sendMonotonicNs": now, "inferenceMs": 100.0,
        "personDetected": True, "landmarks": landmarks, "worldLandmarks": world,
    }


def collect_osc(sock: socket.socket, stop: threading.Event, counts: dict[str, int], errors: list[str]) -> None:
    sock.settimeout(0.1)
    while not stop.is_set():
        try:
            data, _ = sock.recvfrom(4096)
        except socket.timeout:
            continue
        try:
            end = data.index(b"\0")
            path = data[:end].decode("utf-8")
            name = path.removeprefix("/avatar/parameters/")
            tag_start = (end + 4) & ~3
            tag_end = data.index(b"\0", tag_start)
            value = struct.unpack_from(">f", data, (tag_end + 4) & ~3)[0]
            if not path.startswith("/avatar/parameters/") or name not in counts:
                raise ValueError("unexpected OSC address")
            if data[tag_start:tag_end] != b",f" or not math.isfinite(value) or not -1.0 <= value <= 1.0:
                raise ValueError("invalid OSC float")
            counts[name] += 1
        except (ValueError, UnicodeDecodeError, struct.error) as error:
            errors.append(str(error))


def run(duration: float, fps: float) -> dict:
    frame_count = int(duration * fps)
    session = "synthetic-" + uuid.uuid4().hex
    stop = threading.Event()
    osc_counts = dict.fromkeys(PARAMETERS, 0)
    osc_errors: list[str] = []
    receiver_results: list[ReceiverStats] = []
    acked = 0
    bad_acks = 0
    timed_out = 0

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server, \
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as osc, \
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        server.bind(("127.0.0.1", 0))
        osc.bind(("127.0.0.1", 0))
        client.bind(("127.0.0.1", 0))
        client.settimeout(0.5)
        bridge = PoseBridge(osc.getsockname()[1], 3.0, 35.0, 250.0)
        osc_worker = threading.Thread(target=collect_osc, args=(osc, stop, osc_counts, osc_errors))
        receiver_worker = threading.Thread(
            target=lambda: receiver_results.append(serve(server, duration + 1.0, 60.0, "127.0.0.1", bridge))
        )
        osc_worker.start()
        receiver_worker.start()
        started = time.monotonic()
        try:
            for index in range(frame_count):
                due = started + index / fps
                remaining = due - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                frame = synthetic_pose(index + 1, time.monotonic() - started, session)
                client.sendto(json.dumps(frame, separators=(",", ":")).encode("utf-8"), server.getsockname())
                try:
                    raw, _ = client.recvfrom(4096)
                    ack = json.loads(raw)
                    if (ack.get("type") == "ack" and ack.get("session") == session and
                            ack.get("seq") == frame["seq"] and ack.get("sendMonotonicNs") == frame["sendMonotonicNs"]):
                        acked += 1
                    else:
                        bad_acks += 1
                except socket.timeout:
                    timed_out += 1
        finally:
            receiver_worker.join(timeout=5.0)
            stop.set()
            osc_worker.join(timeout=2.0)
        if receiver_worker.is_alive() or osc_worker.is_alive() or not receiver_results:
            raise RuntimeError("Synthetic receiver or OSC collector did not finish")

    stats = receiver_results[0]
    summary = stats.summary(time.monotonic() - started)
    ok = (
        acked == frame_count and bad_acks == 0 and timed_out == 0 and
        stats.accepted == frame_count and stats.malformed == 0 and stats.oversized == 0 and
        stats.missing == 0 and stats.out_of_order == 0 and stats.osc_errors == 0 and
        bridge.controller.baseline is not None and all(osc_counts.values()) and not osc_errors
    )
    return {
        "result": "PASS" if ok else "FAIL",
        "kind": "synthetic_loopback_not_phone_or_vrchat",
        "requested_duration_s": duration,
        "requested_fps": fps,
        "sent": frame_count,
        "acknowledged": acked,
        "ack_timeouts": timed_out,
        "bad_acks": bad_acks,
        "osc_counts": osc_counts,
        "osc_parse_errors": len(osc_errors),
        "receiver": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--fps", type=float, default=15.0)
    args = parser.parse_args()
    if not math.isfinite(args.duration) or not 5.0 <= args.duration <= 3600.0:
        parser.error("duration must be 5..3600 seconds")
    if not math.isfinite(args.fps) or not 1.0 <= args.fps <= 120.0:
        parser.error("fps must be 1..120")
    print("SYNTHETIC LOOPBACK ONLY: no Android device, Wi-Fi, or VRChat is tested.", flush=True)
    result = run(args.duration, args.fps)
    print("SOAK_RESULT " + json.dumps(result, separators=(",", ":")), flush=True)
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
