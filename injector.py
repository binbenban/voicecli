"""Terminal text injection (Phase 5).

The end goal: dictated text lands on the current terminal prompt without Enter.
On a normal Linux desktop you'd fake keystrokes (xdotool / TIOCSTI). Inside WSL
neither is available — there is no /dev/input, `legacy_tiocsti` is disabled, and
Windows owns the physical keyboard. So we use terminal-native mechanisms that
work *without* OS-level keystroke injection:

    tmux      `tmux send-keys -l` inserts literal text into a pane's input line.
              This is the real "types into your prompt" experience and the
              recommended way to run voicecli. No Enter unless configured.
    osc52     An OSC 52 escape sequence copies text into the *terminal's*
              clipboard (works over SSH, Windows Terminal, Kitty, etc.). The
              user pastes with a normal paste. No keystroke injection needed.
    clipboard `clip.exe` puts text on the Windows clipboard (WSL-specific).
    stdout    Just print — for `codex "$(voice)"` command substitution.

`auto` picks tmux when running inside tmux, else osc52, else stdout. Each mode
is a small method; adding a new one (Kitty remote, wl-copy) is one function.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from config import Config

logger = logging.getLogger(__name__)


class InjectionError(RuntimeError):
    """The chosen output mechanism was unavailable or failed."""


@dataclass
class Injector:
    """Sends text to the terminal using the configured output mode."""

    config: Config

    def inject(self, text: str) -> None:
        """Deliver ``text`` via the configured (or auto-detected) output mode."""
        if not text:
            logger.warning("Nothing to inject (empty text)")
            return

        mode = self.config.output_mode
        if mode == "auto":
            mode = self._auto_mode()
        logger.info("Injecting %d chars via %s", len(text), mode)

        dispatch = {
            "tmux": self._inject_tmux,
            "osc52": self._inject_osc52,
            "clipboard": self._inject_clipboard,
            "stdout": self._inject_stdout,
        }
        handler = dispatch.get(mode)
        if handler is None:
            raise InjectionError(f"Unknown output_mode: {mode!r}")
        handler(text)

    @staticmethod
    def _auto_mode() -> str:
        """tmux inside tmux, else osc52 on a TTY, else stdout."""
        if os.environ.get("TMUX"):
            return "tmux"
        if sys.stdout.isatty():
            return "osc52"
        return "stdout"

    # --- tmux: type into the active pane's command line ----------------
    def _inject_tmux(self, text: str) -> None:
        """Insert text into a tmux pane with `send-keys -l` (literal, no Enter).

        `-l` sends the string literally so shell metacharacters aren't
        interpreted as tmux key names. Enter is sent separately only when
        ``tmux_send_enter`` is set.
        """
        if shutil.which("tmux") is None:
            raise InjectionError("output_mode=tmux but tmux is not installed")
        if not (self.config.tmux_target or os.environ.get("TMUX")):
            raise InjectionError(
                "output_mode=tmux but not inside a tmux session and no tmux_target set"
            )

        cmd = ["tmux", "send-keys"]
        if self.config.tmux_target:
            cmd += ["-t", self.config.tmux_target]
        cmd += ["-l", text]  # -l = literal
        self._run(cmd)

        if self.config.tmux_send_enter:
            enter = ["tmux", "send-keys"]
            if self.config.tmux_target:
                enter += ["-t", self.config.tmux_target]
            enter += ["Enter"]
            self._run(enter)

    # --- OSC52: copy to the terminal's clipboard -----------------------
    def _inject_osc52(self, text: str) -> None:
        """Emit an OSC 52 sequence so the terminal copies text to its clipboard.

        Format: ESC ] 52 ; c ; <base64> BEL. The user then pastes normally.
        Works across SSH and in Windows Terminal / Kitty / iTerm2.
        """
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        sys.stdout.write(f"\033]52;c;{b64}\a")
        sys.stdout.flush()
        logger.info("Copied to terminal clipboard (paste to use)")

    # --- Windows clipboard via clip.exe (WSL) --------------------------
    def _inject_clipboard(self, text: str) -> None:
        if shutil.which("clip.exe") is None:
            raise InjectionError("output_mode=clipboard but clip.exe not found (not WSL?)")
        # clip.exe reads stdin. Modern Windows clip handles UTF-8.
        subprocess.run(["clip.exe"], input=text.encode("utf-8"), check=True)
        logger.info("Copied to Windows clipboard")

    # --- stdout --------------------------------------------------------
    @staticmethod
    def _inject_stdout(text: str) -> None:
        print(text)

    @staticmethod
    def _run(cmd: list[str]) -> None:
        logger.debug("Running: %s", " ".join(repr(c) for c in cmd))
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            raise InjectionError(f"Command failed ({exc.returncode}): {cmd[0]}") from exc
