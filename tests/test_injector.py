"""Phase 5 checks: output-mode dispatch and command construction.

Run: .venv/bin/python -m unittest discover -s tests
No real herdr/terminal — we verify which mechanism is chosen and the exact argv
sent, which is where injection bugs live.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config  # noqa: E402
from injector import Injector, InjectionError  # noqa: E402


class AutoModeTests(unittest.TestCase):
    def test_auto_picks_herdr_when_in_herdr(self):
        inj = Injector(Config(output_mode="auto", herdr_target="w1:p5"))
        with mock.patch.dict("injector.os.environ", {"HERDR_ENV": "1"}, clear=True), \
             mock.patch("injector.shutil.which", return_value="/usr/bin/herdr"), \
             mock.patch("injector.subprocess.run") as run:
            inj.inject("hi")
        self.assertEqual(run.call_args.args[0][:3], ["herdr", "pane", "send-text"])

    def test_auto_falls_back_to_stdout(self):
        inj = Injector(Config(output_mode="auto"))
        with mock.patch.dict("injector.os.environ", {}, clear=True), \
             mock.patch("builtins.print") as pr:
            inj.inject("hi")
        pr.assert_called_once_with("hi")


class HerdrTests(unittest.TestCase):
    def test_send_text_uses_configured_target(self):
        inj = Injector(Config(output_mode="herdr", herdr_target="w1:p5"))
        with mock.patch("injector.shutil.which", return_value="/usr/bin/herdr"), \
             mock.patch.dict("injector.os.environ", {}, clear=True), \
             mock.patch("injector.subprocess.run") as run:
            inj.inject("hello")
        run.assert_called_once_with(
            ["herdr", "pane", "send-text", "w1:p5", "hello"], check=True
        )

    def test_send_text_falls_back_to_env_pane(self):
        inj = Injector(Config(output_mode="herdr"))
        with mock.patch("injector.shutil.which", return_value="/usr/bin/herdr"), \
             mock.patch.dict("injector.os.environ", {"HERDR_ACTIVE_PANE_ID": "w2:p9"}, clear=True), \
             mock.patch("injector.subprocess.run") as run:
            inj.inject("hi")
        self.assertEqual(run.call_args.args[0][3], "w2:p9")

    def test_send_text_with_enter(self):
        inj = Injector(Config(output_mode="herdr", herdr_target="w1:p5", send_enter=True))
        with mock.patch("injector.shutil.which", return_value="/usr/bin/herdr"), \
             mock.patch.dict("injector.os.environ", {}, clear=True), \
             mock.patch("injector.subprocess.run") as run:
            inj.inject("ls")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].args[0], ["herdr", "pane", "send-keys", "w1:p5", "enter"])

    def test_herdr_missing_raises(self):
        inj = Injector(Config(output_mode="herdr"))
        with mock.patch("injector.shutil.which", return_value=None):
            with self.assertRaises(InjectionError):
                inj.inject("hi")


class StdoutTests(unittest.TestCase):
    def test_stdout_prints(self):
        inj = Injector(Config(output_mode="stdout"))
        with mock.patch("builtins.print") as pr:
            inj.inject("hi")
        pr.assert_called_once_with("hi")


if __name__ == "__main__":
    unittest.main()
