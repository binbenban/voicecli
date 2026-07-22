"""Audio recording via SoX (Phase 1).

Why SoX and not a Python audio library (sounddevice/pyaudio)?
    * Zero Python audio deps and no ALSA/PortAudio build headaches inside WSL.
    * On WSLg the microphone is exposed through PulseAudio; SoX's default input
      driver already talks to it, so `rec` "just works".
    * SoX ships the silence-detection effect we need in Phase 2, so committing
      to it now avoids swapping backends later.

Phase 1 scope: start a recording, stop it with Ctrl+C, save a WAV file.
The recorder shells out to `rec` (SoX) and lets it write the file directly —
we do not buffer audio in Python.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config import Config, record_pidfile

logger = logging.getLogger(__name__)


class RecorderError(RuntimeError):
    """SoX is missing or the recording process failed."""


@dataclass
class Recorder:
    """Records microphone audio to a WAV file using SoX.

    The Config is injected rather than read from a global, so tests and later
    phases can supply their own settings.
    """

    config: Config

    def __post_init__(self) -> None:
        if shutil.which("rec") is None:
            raise RecorderError(
                "SoX 'rec' not found on PATH. Install with: sudo apt install sox"
            )

    def _output_path(self) -> Path:
        """Timestamped WAV path inside the recordings directory."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        return self.config.recordings_path / f"rec-{stamp}.{self.config.audio_format}"

    def _build_command(self, output: Path) -> list[str]:
        """Assemble the SoX `rec` argv.

        `rec` is SoX's record front-end: it reads from the default audio input
        and writes the given file. We pin channels, sample rate, and format so
        the WAV matches what downstream phases (Whisper) expect.

        When ``stop_on_silence`` is set, effects are appended so SoX ends the
        recording itself (Phase 2). Otherwise recording runs until Ctrl+C.
        """
        device = self.config.sox_input_device
        cmd = ["rec"]
        # "default" means: let SoX pick the PulseAudio default source. Any other
        # value is treated as an explicit device passed via -t pulseaudio.
        if device and device != "default":
            cmd += ["-t", "pulseaudio", device]
        cmd += [
            "-c", str(self.config.channels),
            "-r", str(self.config.sample_rate),
            str(output),
        ]
        cmd += self._silence_effects()
        return cmd

    def _silence_effects(self) -> list[str]:
        """SoX effect chain for auto-stop, empty if disabled.

        ``silence 1 <start_dur> <start_thr> 1 <silence_dur> <silence_thr>``:
          * first triple  — wait for sound above start_thr for start_dur before
            keeping audio (trims leading dead air, so a slow start is fine).
          * second triple — once recording, stop after silence_dur of continuous
            audio below silence_thr (the natural end-of-speech pause).
        ``trim 0 <max_duration>`` is a hard length cap: a safety net so a stuck
        mic or constant background hum can't record forever.
        """
        c = self.config
        if not c.stop_on_silence:
            return []
        return [
            "silence",
            "1", c.start_duration, c.start_threshold,
            "1", c.silence_duration, c.silence_threshold,
            "trim", "0", c.max_duration,
        ]

    def record(self, output: Path | None = None,
               on_ready: Callable[[], None] | None = None,
               pane_id: str = "global") -> Path:
        """Record and return the saved file path.

        With ``stop_on_silence`` the SoX effect chain ends the recording on a
        pause. Otherwise recording runs until the SoX process is signalled —
        another ``main.py --stop`` (the second hotkey press) sends SIGINT via
        the PID written to the per-pane pidfile. SIGINT flushes a valid WAV.

        Args:
            output: Destination file. Defaults to a timestamped name.
            on_ready: Called once the mic is actually capturing (after a short
                warmup), so the "listening" indicator can't show before SoX has
                opened the input device — which would clip the first words.
            pane_id: herdr pane identifier for per-pane recording state.

        Returns:
            Path to the written WAV file.
        """
        from config import record_pidfile
        out = Path(output) if output else self._output_path()
        cmd = self._build_command(out)
        how = "pause to stop" if self.config.stop_on_silence else "hotkey again to stop"
        logger.info("Recording to %s (%s) [pane=%s]", out, how, pane_id)
        logger.debug("SoX command: %s", " ".join(cmd))

        pidfile = record_pidfile(pane_id)
        proc = subprocess.Popen(cmd)
        pidfile.write_text(str(proc.pid))
        # PulseAudio device open + first buffer takes a moment; announce "ready"
        # only after it, so early speech isn't lost.
        time.sleep(self.config.mic_warmup)
        if on_ready is not None and proc.poll() is None:
            on_ready()

        try:
            rc = proc.wait()
        except KeyboardInterrupt:
            proc.wait()  # SoX flushes the WAV header on SIGINT
            rc = 0
        finally:
            pidfile.unlink(missing_ok=True)

        # SoX returns non-zero on SIGINT on some builds; a present, non-empty
        # file is success regardless.
        if rc not in (0, None) and not (out.exists() and out.stat().st_size > 0):
            raise RecorderError(f"SoX recording failed (exit {rc})")

        if not out.exists() or out.stat().st_size == 0:
            raise RecorderError(f"No audio captured: {out} is missing or empty")

        logger.info("Saved %s (%d bytes)", out, out.stat().st_size)
        self._prune_recordings()
        return out

    def _prune_recordings(self) -> None:
        """Remove oldest recordings if max_recordings is exceeded."""
        max_n = self.config.max_recordings
        if max_n <= 0:
            return
        recs = sorted(self.config.recordings_path.glob(f"rec-*.{self.config.audio_format}"),
                      key=lambda p: p.stat().st_mtime)
        while len(recs) > max_n:
            oldest = recs.pop(0)
            oldest.unlink(missing_ok=True)
            logger.info("Pruned old recording: %s", oldest)
