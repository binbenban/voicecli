"""Terminal text injection (Phase 5).

The end goal: dictated text lands on the current terminal prompt without Enter.
On a normal Linux desktop you'd fake keystrokes (xdotool / TIOCSTI). Inside WSL
neither is available — there is no /dev/input, `legacy_tiocsti` is disabled, and
Windows owns the physical keyboard. So we use herdr's socket API, which types
into a pane without any OS-level keystroke injection:

    herdr   `herdr pane send-text` inserts literal text into a pane's input
            line. No Enter unless `send_enter` is set.
    stdout  Just print — for `codex "$(voice)"` command substitution, or when
            not running inside herdr.

`auto` picks herdr when running inside herdr, else stdout.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

from config import Config

logger = logging.getLogger(__name__)


class InjectionError(RuntimeError):
    """The chosen output mechanism was unavailable or failed."""


def _herdr_current_pane() -> str:
    """Resolve the focused herdr pane id (e.g. "w1:p5"), or "" on failure.

    `herdr pane current` returns JSON; we pull result.pane.pane_id.
    """
    try:
        out = subprocess.run(["herdr", "pane", "current"],
                             capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    try:
        return json.loads(out)["result"]["pane"]["pane_id"]
    except (ValueError, KeyError):
        return ""


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
            mode = "herdr" if os.environ.get("HERDR_ENV") else "stdout"
        logger.info("Injecting %d chars via %s", len(text), mode)

        if mode == "herdr":
            self._inject_herdr(text)
        elif mode == "stdout":
            print(text)
        else:
            raise InjectionError(f"Unknown output_mode: {mode!r}")

    def _inject_herdr(self, text: str) -> None:
        """Insert literal text into a herdr pane with `herdr pane send-text`.

        Target pane comes from herdr_target, else the pane herdr exposes in a
        key-command env ($HERDR_ACTIVE_PANE_ID; interactive shells use
        $HERDR_PANE_ID), else the currently-focused pane (`herdr pane current`).
        """
        if shutil.which("herdr") is None:
            raise InjectionError("output_mode=herdr but herdr is not installed")
        pane = (self.config.herdr_target
                or os.environ.get("HERDR_ACTIVE_PANE_ID")
                or os.environ.get("HERDR_PANE_ID")
                or _herdr_current_pane())
        if not pane:
            raise InjectionError("output_mode=herdr but no target pane could be resolved")
        self._run(["herdr", "pane", "send-text", pane, text])
        if self.config.send_enter:
            self._run(["herdr", "pane", "send-keys", pane, "enter"])

    @staticmethod
    def _run(cmd: list[str]) -> None:
        logger.debug("Running: %s", " ".join(repr(c) for c in cmd))
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            raise InjectionError(f"Command failed ({exc.returncode}): {cmd[0]}") from exc
