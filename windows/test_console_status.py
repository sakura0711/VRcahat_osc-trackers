import contextlib
import io
import os
import unittest
from unittest import mock

from console_status import StatusConsole


class StatusConsoleTests(unittest.TestCase):
    def test_color_is_only_for_human_lines_when_requested(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            StatusConsole("never").emit("check", "等待封包")
            StatusConsole("always").emit("ready", "開始傳送")
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[0], "[check] 等待封包")
        self.assertEqual(lines[1], "\x1b[32m[ready]\x1b[0m 開始傳送")

    def test_auto_respects_no_color(self):
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}), contextlib.redirect_stdout(output):
            StatusConsole("auto").emit("loading", "校正中")
        self.assertEqual(output.getvalue(), "[loading] 校正中\n")


if __name__ == "__main__":
    unittest.main()
