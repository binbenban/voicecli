"""voicecli entry point.

Wires the full pipeline: record (SoX, silence auto-stop) → transcribe
(faster-whisper) → clean + spoken aliases → inject into the terminal
(tmux/OSC52/clipboard/stdout). Also installs the tmux push-to-talk hotkey.
Each stage lives in its own module; this file only orchestrates.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import shutil
import subprocess

from config import load_config, PROJECT_ROOT
from recorder import Recorder, RecorderError

LOG_FILE = PROJECT_ROOT / ".voicecli.log"


def _stop_recording(pane_id: str = "global") -> int:
    """SIGINT the recording SoX process (via its per-pane pidfile). The recording run
    exits its wait, flushes the WAV, and proceeds to transcribe."""
    import os
    import signal

    from config import record_pidfile

    pidfile = record_pidfile(pane_id)
    if not pidfile.exists():
        logging.info("No recording in progress for pane %s", pane_id)
        return 0
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, signal.SIGINT)
        logging.info("Stopped recording (pid %d)", pid)
    except (ValueError, ProcessLookupError):
        pidfile.unlink(missing_ok=True)  # stale pidfile
    return 0


def _notify(config, msg: str, hold_ms: int = 2000) -> None:
    """Show a stage indicator. Background hotkey runs hide stdout, so the only
    way the user sees state is a message on the target pane. Falls back to
    stderr when not driving a multiplexer pane.

    hold_ms overrides tmux's default 750ms display-time. Each stage's message
    replaces the previous one, so a long hold on listening/transcribing just
    stops it vanishing mid-stage — the next stage overwrites it regardless.
    """
    if config.output_mode == "tmux" and config.tmux_target and shutil.which("tmux"):
        subprocess.run(["tmux", "display-message", "-d", str(hold_ms),
                        "-t", config.tmux_target, msg], check=False)
    elif config.output_mode == "herdr" and shutil.which("herdr"):
        subprocess.run(["herdr", "notification", "show", msg], check=False)
    else:
        print(msg, file=sys.stderr, flush=True)


def _herdr_current_pane_id() -> str:
    """Focused herdr pane id, resolved via the injector helper."""
    from injector import _herdr_current_pane
    return _herdr_current_pane()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="voicecli", description="Terminal voice input tool")
    parser.add_argument("-c", "--config", default=None, help="Path to config.yaml")
    parser.add_argument("-o", "--output", default=None, help="Output WAV path")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    parser.add_argument("--record-only", action="store_true",
                        help="Record and print the WAV path; skip transcription")
    parser.add_argument("-f", "--file", default=None,
                        help="Transcribe an existing audio file instead of recording")
    parser.add_argument("--print", dest="force_print", action="store_true",
                        help="Force stdout output (for `codex \"$(voice)\"`), overriding output_mode")
    parser.add_argument("--target", default=None,
                        help="tmux pane to inject into (sets output_mode=tmux). "
                             "Used by the F9 keybinding, which passes #{pane_id}.")
    parser.add_argument("--herdr-target", default=None,
                        help="herdr pane to inject into (sets output_mode=herdr). "
                             "Empty string = resolve the focused pane at runtime.")
    parser.add_argument("--stop", action="store_true",
                        help="Stop the in-progress recording (second hotkey press), then exit")
    parser.add_argument("--pane-id", default=None,
                        help="tmux pane ID for per-pane stop (used by hotkey toggle)")
    parser.add_argument("--install-hotkey", action="store_true",
                        help="Bind the configured hotkey in the running tmux server, then exit")
    parser.add_argument("--uninstall-hotkey", action="store_true",
                        help="Remove the tmux hotkey binding, then exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    level = logging.DEBUG if args.verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt)
    # File handler: always log to .voicecli.log for diagnosability.
    # run-shell -b swallows stderr, so without this errors vanish silently.
    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(fmt))
    logging.getLogger().addHandler(fh)
    # Silence chatty third-party debug logs (HF download, httpx) even under -v.
    for noisy in ("httpx", "httpcore", "filelock", "urllib3", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    config = load_config(args.config)

    # --stop is the second hotkey press: signal the running recorder and exit.
    if args.stop:
        return _stop_recording(args.pane_id or "global")

    # Hotkey management short-circuits the pipeline.
    if args.install_hotkey or args.uninstall_hotkey:
        from hotkey import HotkeyInstaller

        installer = HotkeyInstaller(config)
        if args.uninstall_hotkey:
            installer.uninstall()
        else:
            installer.install()
            # herdr's install() already printed its config.toml block; tmux needs
            # the ~/.tmux.conf line to persist across sessions.
            import os as _os
            if not _os.environ.get("HERDR_ENV"):
                print("Persist across sessions by adding this to ~/.tmux.conf:")
                print("  " + installer.config_line())
        return 0

    # A --target pane forces tmux injection into that pane (used by the F9 bind).
    if args.target:
        config.output_mode = "tmux"
        config.tmux_target = args.target
    # --herdr-target does the same for herdr (may be "" → resolve at runtime).
    elif args.herdr_target is not None:
        config.output_mode = "herdr"
        config.herdr_target = args.herdr_target or _herdr_current_pane_id()

    # 1. Obtain audio: either an existing file or a fresh recording.
    if args.file:
        audio_path = Path(args.file)
    else:
        # Announce "listening" only once the mic is actually capturing (via
        # on_ready), so early words aren't clipped. Hold the message for the
        # whole possible recording (max_duration + margin) so it doesn't vanish.
        listen_ms = (int(float(config.max_duration)) + 5) * 1000
        stop_how = "pause to stop" if config.stop_on_silence else "press hotkey again to stop"
        ready = lambda: _notify(config, f"🎤 voicecli: listening… ({stop_how})",
                                hold_ms=listen_ms)
        # Derive pane_id from target for per-pane recording state.
        pane_id = config.tmux_target or config.herdr_target or "global"
        try:
            audio_path = Recorder(config).record(output=args.output, on_ready=ready,
                                                 pane_id=pane_id)
        except RecorderError as exc:
            logging.error("%s", exc)
            _notify(config, f"❌ voicecli: {exc}")
            return 1

    if args.record_only:
        print(audio_path)
        return 0

    # 2. Transcribe. Prefer the warm-model daemon (skips the multi-second model
    #    load); fall back to a local load if it's not up yet, then spawn it so
    #    the next press is warm. Imported here so record-only stays dep-free.
    _notify(config, "✍️  voicecli: transcribing…", hold_ms=60000)
    text = None
    if config.use_daemon:
        from daemon import spawn_daemon, transcribe_via_daemon

        try:
            text = transcribe_via_daemon(config, audio_path)
        except RuntimeError as exc:
            logging.error("Daemon error: %s", exc)  # fall through to local
    if text is None:
        from transcriber import Transcriber

        text = Transcriber(config).transcribe(audio_path)
        if config.use_daemon:
            spawn_daemon()  # warm up for next time
    if not text:
        logging.warning("Empty transcript (silence or too-quiet audio)")

    # 3. Clean up transcript + apply spoken aliases.
    from cleaner import Cleaner

    text = Cleaner(config).clean(text)

    # 4. Deliver: inject into the terminal, or plain stdout for $(voice).
    from injector import Injector, InjectionError

    if args.force_print:
        print(text)
        return 0
    try:
        Injector(config).inject(text)
    except InjectionError as exc:
        logging.error("%s", exc)
        _notify(config, f"❌ voicecli: {exc}")
        print(text)  # never lose the transcript: fall back to stdout
        return 1
    _notify(config, "✅ voicecli: inserted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
