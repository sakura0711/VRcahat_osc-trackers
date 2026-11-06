"""Small human-readable status lines alongside stable JSON receiver reports."""

from __future__ import annotations

import os
import sys


COLORS = {
    "check": "36",    # cyan
    "loading": "33",  # yellow
    "ready": "32",    # green
    "wait": "33",
    "lost": "31",     # red
    "error": "31",
}


class StatusConsole:
    def __init__(self, color: str = "auto") -> None:
        if color not in ("auto", "always", "never"):
            raise ValueError("color must be auto, always, or never")
        self.color = color

    def emit(self, label: str, message: str, *, error: bool = False) -> None:
        stream = sys.stderr if error else sys.stdout
        use_color = self.color == "always" or (
            self.color == "auto" and "NO_COLOR" not in os.environ
            and stream.isatty() and os.environ.get("TERM") != "dumb"
            and (os.name != "nt" or bool(os.environ.get("WT_SESSION") or
                                             os.environ.get("ANSICON") or
                                             os.environ.get("ConEmuANSI") == "ON" or
                                             os.environ.get("TERM", "").startswith("xterm")))
        )
        prefix = f"[{label}]"
        if use_color and label in COLORS:
            prefix = f"\x1b[{COLORS[label]}m{prefix}\x1b[0m"
        print(f"{prefix} {message}", file=stream, flush=True)
