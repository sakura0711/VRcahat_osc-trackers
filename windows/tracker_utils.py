"""Shared confidence and OSC string encoding for native tracker output."""

from __future__ import annotations

from typing import Any


def point_confident(point: dict[str, Any], threshold: float) -> bool:
    available = [point.get(key) for key in ("visibility", "presence") if point.get(key) is not None]
    return bool(available) and min(available) >= threshold


def osc_string(value: str) -> bytes:
    encoded = value.encode("utf-8") + b"\x00"
    return encoded + b"\x00" * (-len(encoded) % 4)
