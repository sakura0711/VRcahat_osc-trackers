"""Send temporary test parameters to a locally running VRChat client.

This is a manual visual diagnostic, not evidence that VRChat received OSC.
Stop the pose receiver while using it so that the two senders do not compete.
"""

from __future__ import annotations

import argparse
import time

from pose_control import IDLE_VALUES, OscOutput, PARAMETERS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parameters", nargs="+", choices=[name.removeprefix("Puppet/") for name in PARAMETERS])
    parser.add_argument("--value", type=float, default=1.0, help="test value from -1 to 1 (default: 1)")
    parser.add_argument("--hold", type=float, default=5.0, help="seconds to hold the value (default: 5)")
    parser.add_argument("--port", type=int, default=9000, help="local VRChat OSC input port (default: 9000)")
    args = parser.parse_args()
    if not -1 <= args.value <= 1 or not 0 < args.hold <= 30 or not 1 <= args.port <= 65535:
        parser.error("value must be -1..1, hold must be >0 and <=30 seconds, and port must be 1..65535")

    output = OscOutput(args.port)
    idle = dict(IDLE_VALUES)
    values = {"Puppet/" + name: args.value for name in args.parameters}
    try:
        output.send(idle)
        time.sleep(0.5)
        print(f"Sending {values} for {args.hold:g} seconds; observe the avatar in VRChat.", flush=True)
        until = time.monotonic() + args.hold
        while time.monotonic() < until:
            output.send(values)
            time.sleep(min(0.1, max(0.0, until - time.monotonic())))
    finally:
        try:
            output.send(idle)
        finally:
            output.close()
        print("Sent idle values. UDP send does not confirm that VRChat received them.", flush=True)


if __name__ == "__main__":
    main()
