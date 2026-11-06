"""Explicit, local-only OSC output for calibrated VRChat tracker transforms.

The caller must supply world-space positions in metres, Euler rotations in
degrees, and a role-to-ID mapping verified during VRChat FBT calibration.
This module does not derive transforms from phone landmarks.
"""

from __future__ import annotations

import math
import socket
import struct
from dataclasses import dataclass
from typing import Mapping

from tracker_utils import osc_string


ROLES = ("hip", "left_foot", "right_foot")
Vector3 = tuple[float, float, float]


def osc_vector(slot: int, kind: str, values: Vector3) -> bytes:
    """Encode one VRChat OSC Tracker Vector3 message."""
    if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= 8:
        raise ValueError("tracker ID must be 1..8")
    if kind not in ("position", "rotation"):
        raise ValueError("tracker transform must be position or rotation")
    try:
        if len(values) != 3 or any(isinstance(value, bool) for value in values):
            raise ValueError("expected three numeric values")
        vector = tuple(float(value) for value in values)
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("tracker values must be finite")
        packed = struct.pack(">fff", *vector)
    except (TypeError, OverflowError, struct.error) as error:
        raise ValueError("expected three finite float32 values") from error
    return osc_string(f"/tracking/trackers/{slot}/{kind}") + osc_string(",fff") + packed


@dataclass(frozen=True)
class TrackerTransform:
    position: Vector3
    rotation: Vector3


class TrackerOutput:
    """Send supplied tracker transforms to VRChat's localhost OSC input."""

    def __init__(self, slots: Mapping[str, int], port: int = 9000) -> None:
        if set(slots) != set(ROLES) or len(set(slots.values())) != len(ROLES):
            raise ValueError("supply distinct IDs for hip, left_foot and right_foot")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("OSC port must be 1..65535")
        for slot in slots.values():
            if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= 8:
                raise ValueError("tracker ID must be 1..8")
        self.slots = dict(slots)
        self.address = ("127.0.0.1", port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, transforms: Mapping[str, TrackerTransform]) -> int:
        """Send only supplied roles; return datagram count. Invalid batches send nothing."""
        if set(transforms) - set(ROLES):
            raise ValueError("unknown tracker role")
        messages = []
        for role in ROLES:
            if role in transforms:
                transform = transforms[role]
                messages.append(osc_vector(self.slots[role], "position", transform.position))
                messages.append(osc_vector(self.slots[role], "rotation", transform.rotation))
        for message in messages:
            self.socket.sendto(message, self.address)
        return len(messages)

    def close(self) -> None:
        self.socket.close()
