"""Phase 2 checks: SoX silence-effect construction.

Run: .venv/bin/python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config  # noqa: E402
from recorder import Recorder  # noqa: E402


class SilenceEffectTests(unittest.TestCase):
    def setUp(self):
        self.which = mock.patch("recorder.shutil.which", return_value="/usr/bin/rec")
        self.which.start()

    def tearDown(self):
        self.which.stop()

    def test_silence_effects_appended_when_enabled(self):
        rec = Recorder(Config(
            stop_on_silence=True,
            start_duration="0.1", start_threshold="3%",
            silence_duration="1.5", silence_threshold="3%",
            max_duration="30",
        ))
        cmd = rec._build_command(Path("/tmp/x.wav"))
        self.assertEqual(
            cmd[-10:],
            ["silence", "1", "0.1", "3%", "1", "1.5", "3%", "trim", "0", "30"],
        )

    def test_no_effects_when_disabled(self):
        rec = Recorder(Config(stop_on_silence=False))
        cmd = rec._build_command(Path("/tmp/x.wav"))
        self.assertNotIn("silence", cmd)


if __name__ == "__main__":
    unittest.main()
