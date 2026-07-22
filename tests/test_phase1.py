"""Phase 1 checks: config loading and SoX command construction.

Run: .venv/bin/python -m unittest discover -s tests
These do not touch the microphone — they verify the logic that surrounds SoX,
which is where bugs actually hide. The mic path is verified manually (see README).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config, load_config  # noqa: E402
from recorder import Recorder, RecorderError  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_defaults_when_file_missing(self):
        cfg = load_config("/nonexistent/config.yaml")
        self.assertEqual(cfg.sample_rate, 16000)
        self.assertEqual(cfg.channels, 1)

    def test_yaml_overrides_and_unknown_keys_ignored(self, tmp=None):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("sample_rate: 44100\nfuture_option: whatever\n")
            path = f.name
        cfg = load_config(path)
        self.assertEqual(cfg.sample_rate, 44100)  # override applied
        self.assertFalse(hasattr(cfg, "future_option"))  # unknown key dropped

    def test_non_mapping_yaml_rejected(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("- just\n- a\n- list\n")
            path = f.name
        with self.assertRaises(ValueError):
            load_config(path)


class ConfigValidationTests(unittest.TestCase):
    def test_valid_config_passes(self):
        cfg = Config()
        errors = cfg.validate()
        self.assertEqual(errors, [])

    def test_invalid_sample_rate(self):
        cfg = Config(sample_rate=-1)
        errors = cfg.validate()
        self.assertTrue(any("sample_rate" in e for e in errors))

    def test_invalid_channels(self):
        cfg = Config(channels=5)
        errors = cfg.validate()
        self.assertTrue(any("channels" in e for e in errors))

    def test_invalid_beam_size(self):
        cfg = Config(beam_size=0)
        errors = cfg.validate()
        self.assertTrue(any("beam_size" in e for e in errors))

    def test_invalid_output_mode(self):
        cfg = Config(output_mode="invalid")
        errors = cfg.validate()
        self.assertTrue(any("output_mode" in e for e in errors))

    def test_invalid_device(self):
        cfg = Config(device="tpu")
        errors = cfg.validate()
        self.assertTrue(any("device" in e for e in errors))

    def test_invalid_max_recordings(self):
        cfg = Config(max_recordings=-1)
        errors = cfg.validate()
        self.assertTrue(any("max_recordings" in e for e in errors))

    def test_invalid_mic_warmup(self):
        cfg = Config(mic_warmup=-1.0)
        errors = cfg.validate()
        self.assertTrue(any("mic_warmup" in e for e in errors))


class RecordPidfileTests(unittest.TestCase):
    def test_global_pidfile(self):
        from config import record_pidfile
        pidfile = record_pidfile("global")
        self.assertTrue(pidfile.name.endswith(".pid"))
        self.assertIn("global", pidfile.name)

    def test_pane_id_sanitized(self):
        from config import record_pidfile
        pidfile = record_pidfile("%5")
        self.assertIn("%5", pidfile.name)
        self.assertNotIn(":", pidfile.name)

    def test_complex_pane_id(self):
        from config import record_pidfile
        pidfile = record_pidfile("mysess:0.1")
        self.assertIn("mysess_0_1", pidfile.name)


class RecorderCommandTests(unittest.TestCase):
    def setUp(self):
        # shutil.which('rec') must pass for construction; pretend it exists.
        self.which = mock.patch("recorder.shutil.which", return_value="/usr/bin/rec")
        self.which.start()

    def tearDown(self):
        self.which.stop()

    def test_default_device_command(self):
        # stop_on_silence=False isolates the base argv (silence effects tested
        # separately in test_phase2).
        rec = Recorder(Config(sample_rate=16000, channels=1, stop_on_silence=False))
        cmd = rec._build_command(Path("/tmp/x.wav"))
        self.assertEqual(cmd, ["rec", "-c", "1", "-r", "16000", "/tmp/x.wav"])

    def test_explicit_device_uses_pulseaudio(self):
        rec = Recorder(Config(sox_input_device="RDPSource", stop_on_silence=False))
        cmd = rec._build_command(Path("/tmp/x.wav"))
        self.assertEqual(cmd[:3], ["rec", "-t", "pulseaudio"])
        self.assertIn("RDPSource", cmd)

    def test_missing_sox_raises(self):
        with mock.patch("recorder.shutil.which", return_value=None):
            with self.assertRaises(RecorderError):
                Recorder(Config())

    def test_empty_output_is_error(self):
        rec = Recorder(Config(stop_on_silence=False))
        with mock.patch("recorder.subprocess.Popen") as popen:
            popen.return_value.poll.return_value = 0
            popen.return_value.wait.return_value = 0
            with self.assertRaises(RecorderError):
                rec.record(output=Path("/tmp/does-not-exist-voicecli.wav"))


if __name__ == "__main__":
    unittest.main()
