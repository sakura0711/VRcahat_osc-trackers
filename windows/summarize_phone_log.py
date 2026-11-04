"""Summarize Pose Landmarker callback-rate windows from a filtered Android logcat."""

from __future__ import annotations

import argparse
import codecs
import json
import math
from pathlib import Path
import re
from typing import Iterable

RATE = re.compile(
    r"\bPOSE_RATE delegate=(\w+) durationMs=(\d+(?:\.\d+)?) "
    r"results=(\d+) poses=(\d+) resultFps=\S+ poseFps=\S+"
)
UDP = re.compile(
    r"\bUDP sent=(\d+) ack=(\d+) overwritten=(\d+) expired=(\d+) "
    r"rttP50Ms=(\S+) rttP95Ms=(\S+) bytes=(\d+) recentAck=(true|false)"
)


def summarize(lines: Iterable[str], threshold_fps: float = 15.0) -> dict:
    delegates: dict[str, dict] = {}
    last_udp = None
    rejected = 0
    for line in lines:
        match = RATE.search(line)
        if match:
            delegate, duration_text, result_text, pose_text = match.groups()
            duration_ms = float(duration_text)
            results, poses = int(result_text), int(pose_text)
            if not math.isfinite(duration_ms) or duration_ms <= 0 or results <= 0 or poses > results:
                rejected += 1
                continue
            entry = delegates.setdefault(delegate, {
                "windows": 0, "duration_ms": 0.0, "results": 0, "poses": 0,
                "min_result_fps": None, "windows_below_threshold": 0,
            })
            fps = results * 1000.0 / duration_ms
            entry["windows"] += 1
            entry["duration_ms"] += duration_ms
            entry["results"] += results
            entry["poses"] += poses
            entry["min_result_fps"] = fps if entry["min_result_fps"] is None else min(entry["min_result_fps"], fps)
            if fps < threshold_fps:
                entry["windows_below_threshold"] += 1
        match = UDP.search(line)
        if match:
            sent, ack, overwritten, expired, p50, p95, size, recent = match.groups()
            last_udp = {
                "sent": int(sent), "ack": int(ack), "overwritten": int(overwritten),
                "expired": int(expired), "rtt_p50_ms_recent_512": None if p50 == "none" else float(p50),
                "rtt_p95_ms_recent_512": None if p95 == "none" else float(p95),
                "last_bytes": int(size), "recent_ack": recent == "true",
            }
    for entry in delegates.values():
        duration_ms = entry.pop("duration_ms")
        entry["window_seconds"] = round(duration_ms / 1000.0, 3)
        entry["result_fps"] = round(entry["results"] * 1000.0 / duration_ms, 2)
        entry["pose_fps"] = round(entry["poses"] * 1000.0 / duration_ms, 2)
        entry["min_result_fps"] = round(entry["min_result_fps"], 2)
    return {
        "kind": "phone_callback_windows_not_camera_fps_or_end_to_end",
        "fps_threshold": threshold_fps,
        "by_delegate": delegates,
        "rejected_rate_windows": rejected,
        "last_udp_status": last_udp,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="filtered logcat output from one continuous run")
    parser.add_argument("--threshold-fps", type=float, default=15.0)
    args = parser.parse_args()
    if not math.isfinite(args.threshold_fps) or args.threshold_fps <= 0:
        parser.error("--threshold-fps must be finite and positive")
    try:
        raw = args.log.read_bytes()
        encoding = "utf-16" if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig"
        text = raw.decode(encoding, errors="replace")
    except OSError as error:
        parser.error(str(error))
    result = summarize(text.splitlines(), args.threshold_fps)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["by_delegate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
