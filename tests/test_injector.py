"""Phase 5 checks: output-mode dispatch and command construction.

Run: .venv/bin/python -m unittest discover -s tests
No real tmux/terminal — we verify which mechanism is chosen and the exact argv
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
        inj = Injector(Config(output_mode="auto"))
        with mock.patch.dict("injector.os.environ", {"HERDR_ENV": "1"}, clear=True):
            self.assertEqual(inj._auto_mode(), "herdr")

    def test_auto_picks_tmux_when_in_tmux(self):
        inj = Injector(Config(output_mode="auto"))
        with mock.patch.dict("injector.os.environ", {"TMUX": "/tmp/x"}, clear=True):
            self.assertEqual(inj._auto_mode(), "tmux")

    def test_auto_picks_osc52_on_tty(self):
        inj = Injector(Config(output_mode="auto"))
        with mock.patch.dict("injector.os.environ", {}, clear=True), \
             mock.patch("injector.sys.stdout.isatty", return_value=True):
            self.assertEqual(inj._auto_mode(), "osc52")

    def test_auto_falls_back_to_stdout(self):
        inj = Injector(Config(output_mode="auto"))
        with mock.patch.dict("injector.os.environ", {}, clear=True), \
             mock.patch("injector.sys.stdout.isatty", return_value=False):
            self.assertEqual(inj._auto_mode(), "stdout")


class TmuxTests(unittest.TestCase):
    def test_send_keys_literal_no_enter(self):
        inj = Injector(Config(output_mode="tmux", tmux_send_enter=False))
        with mock.patch("injector.shutil.which", return_value="/usr/bin/tmux"), \
             mock.patch.dict("injector.os.environ", {"TMUX": "/tmp/x"}, clear=False), \
             mock.patch("injector.subprocess.run") as run:
            inj.inject("hello world")
        run.assert_called_once_with(
            ["tmux", "send-keys", "-l", "hello world"], check=True
        )

    def test_send_keys_with_enter(self):
        inj = Injector(Config(output_mode="tmux", tmux_send_enter=True))
        with mock.patch("injector.shutil.which", return_value="/usr/bin/tmux"), \
             mock.patch.dict("injector.os.environ", {"TMUX": "/tmp/x"}, clear=False), \
             mock.patch("injector.subprocess.run") as run:
            inj.inject("ls")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].args[0][-1], "Enter")

    def test_tmux_target_flag(self):
        inj = Injector(Config(output_mode="tmux", tmux_target="mysess:0.1"))
        with mock.patch("injector.shutil.which", return_value="/usr/bin/tmux"), \
             mock.patch.dict("injector.os.environ", {}, clear=True), \
             mock.patch("injector.subprocess.run") as run:
            inj.inject("hi")
        argv = run.call_args.args[0]
        self.assertEqual(argv[:4], ["tmux", "send-keys", "-t", "mysess:0.1"])

    def test_tmux_missing_raises(self):
        inj = Injector(Config(output_mode="tmux"))
        with mock.patch("injector.shutil.which", return_value=None):
            with self.assertRaises(InjectionError):
                inj.inject("hi")


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
             mock.patch.dict("injector.os.environ", {"HERDR_PANE_ID": "w2:p9"}, clear=True), \
             mock.patch("injector.subprocess.run") as run:
            inj.inject("hi")
        self.assertEqual(run.call_args.args[0][3], "w2:p9")

    def test_send_text_with_enter(self):
        inj = Injector(Config(output_mode="herdr", herdr_target="w1:p5", tmux_send_enter=True))
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


class Osc52Tests(unittest.TestCase):
    def test_osc52_emits_base64_escape(self):
        inj = Injector(Config(output_mode="osc52"))
        with mock.patch("injector.sys.stdout") as out:
            inj.inject("hi")
        written = out.write.call_args.args[0]
        # base64("hi") == "aGk=", wrapped in OSC52.
        self.assertEqual(written, "\033]52;c;aGk=\a")


if __name__ == "__main__":
    unittest.main()
