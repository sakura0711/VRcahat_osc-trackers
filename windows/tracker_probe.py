"""Phase 0: stream synthetic hip and feet poses to local VRChat over OSC.

This is a manual feasibility probe, independent of the phone and receiver.
Sending UDP does not prove that VRChat received or synchronized the poses.
"""
from __future__ import annotations

import argparse
import math
import queue
import socket
import sys
import threading
import time

from tracker_output import osc_vector


def vector_message(slot: int, kind: str, values: tuple[float, float, float]) -> bytes:
    if slot not in (1, 3, 4) or kind not in ("position", "rotation"):
        raise ValueError("unsupported tracker or transform")
    return osc_vector(slot, kind, values)


def pose(height: float, raised: bool) -> dict[int, tuple[float, float, float]]:
    # Synthetic standing proportions; the real calibration must determine alignment.
    return {
        1: (0.0, height * 0.53, 0.0),
        3: (-height * 0.10, height * (0.24 if raised else 0.04), height * (0.12 if raised else 0.0)),
        4: (height * 0.10, height * 0.04, 0.0),
    }


def send_pose(sock: socket.socket, address: tuple[str, int], height: float, raised: bool) -> None:
    for slot, position in pose(height, raised).items():
        sock.sendto(vector_message(slot, "position", position), address)
        sock.sendto(vector_message(slot, "rotation", (0.0, 0.0, 0.0)), address)


def stream_interactive(sock: socket.socket, address: tuple[str, int], height: float, max_seconds: float) -> None:
    """Keep sending while stdin commands select the next synthetic pose."""
    commands: queue.SimpleQueue[str] = queue.SimpleQueue()

    def read_commands() -> None:
        for line in sys.stdin:
            commands.put(line.strip().lower())
        commands.put("quit")

    threading.Thread(target=read_commands, daemon=True).start()
    raised = False
    deadline = time.monotonic() + max_seconds
    print("Standing. Type 'raise', 'stand', or 'quit' then Enter.", flush=True)
    while time.monotonic() < deadline:
        while not commands.empty():
            command = commands.get_nowait()
            if command == "quit":
                return
            if command in ("raise", "stand"):
                raised = command == "raise"
                print(f"{time.strftime('%H:%M:%S')} {'tracker 3 raised' if raised else 'standing'}", flush=True)
            elif command:
                print("Unknown command. Use 'raise', 'stand', or 'quit'.", flush=True)
        send_pose(sock, address, height, raised)
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    print("Interactive timeout reached.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--height", type=float, default=1.7, help="real height in metres (default: 1.7)")
    parser.add_argument("--port", type=int, default=9000, help="local OSC input port (default: 9000)")
    parser.add_argument("--calibration-seconds", type=float, default=60, help="standing time before changes (default: 60)")
    parser.add_argument("--pose-seconds", type=float, default=15, help="duration of each raised/standing pose (default: 15)")
    parser.add_argument("--cycles", type=int, default=2, help="raised then standing cycles (default: 2)")
    parser.add_argument("--interactive", action="store_true", help="hold standing until stdin commands change the pose")
    parser.add_argument("--max-seconds", type=float, default=600, help="interactive safety timeout (default: 600)")
    args = parser.parse_args()
    if not math.isfinite(args.height) or not 1.0 <= args.height <= 2.5:
        parser.error("height must be finite and between 1.0 and 2.5 metres")
    if not 1 <= args.port <= 65535 or not 1 <= args.cycles <= 100:
        parser.error("port must be 1..65535 and cycles 1..100")
    if not all(math.isfinite(value) and 1 <= value <= 600 for value in (args.calibration_seconds, args.pose_seconds)):
        parser.error("calibration and pose durations must be finite and 1..600 seconds")
    if not math.isfinite(args.max_seconds) or not 1 <= args.max_seconds <= 3600:
        parser.error("max seconds must be finite and 1..3600")

    phases = [("standing for calibration", False, args.calibration_seconds)]
    if not args.interactive:
        for _ in range(args.cycles):
            phases.extend((("tracker 3 raised", True, args.pose_seconds), ("standing", False, args.pose_seconds)))
    print(f"Sending to 127.0.0.1:{args.port} at 20 Hz; height={args.height:g} m. Ctrl+C stops.", flush=True)
    print("UDP sends do not confirm VRChat receipt. No head alignment data is sent.", flush=True)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            address = ("127.0.0.1", args.port)
            if args.interactive:
                stream_interactive(sock, address, args.height, args.max_seconds)
            else:
                for label, raised, duration in phases:
                    print(f"{label}: {duration:g} seconds", flush=True)
                    end = time.monotonic() + duration
                    while time.monotonic() < end:
                        send_pose(sock, address, args.height, raised)
                        time.sleep(min(0.05, max(0.0, end - time.monotonic())))
    except KeyboardInterrupt:
        print("Interrupted.", flush=True)
    finally:
        print("Stopped sending; VRChat may retain tracker data temporarily.", flush=True)


if __name__ == "__main__":
    main()
