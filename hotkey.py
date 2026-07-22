"""Push-to-talk hotkey via tmux keybindings (Phase 6).

Why tmux and not a global hotkey?
    A true "hold F9 anywhere" hotkey needs OS-level keyboard access. Inside WSL
    that is unavailable: there is no /dev/input (no evdev), `legacy_tiocsti` is
    disabled (no TIOCSTI keystroke injection), and the physical keyboard is owned
    by Windows — the Linux side never even sees a key-release event. So a
    press-and-hold gesture cannot be observed here.

    tmux, however, sees every keypress inside its panes. Binding the hotkey in
    tmux gives a terminal-native push-to-talk: press the key, speak, and the
    Phase 2 silence detector ends the recording automatically. The transcript is
    injected straight back into the pane you pressed it in.

This module doesn't run a listener; it *installs* a tmux binding that shells out
to `main.py`. That keeps voicecli stateless — no background daemon to manage.

For literal hold-to-talk, a Windows-side helper (AutoHotkey) is the only path;
see README "Push-to-talk". This module covers the in-WSL experience.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

from config import Config, PROJECT_ROOT

logger = logging.getLogger(__name__)


@dataclass
class HotkeyInstaller:
    """Installs/removes the tmux keybinding that triggers dictation."""

    config: Config

    def __post_init__(self) -> None:
        if shutil.which("tmux") is None:
            raise RuntimeError("tmux is required for the hotkey. Install: sudo apt install tmux")

    def _shell_command(self) -> str:
        """Shell run by the tmux bind on keypress.

        Delegates to hotkey.sh to avoid tmux's $-escaping nightmares.
        The script receives #{pane_id} as $1.
        """
        script = PROJECT_ROOT / "hotkey.sh"
        return f'"{script}" "#{{pane_id}}"'

    def _prefix_flag(self) -> list[str]:
        """`-n` (no prefix, bare key) unless hotkey_prefix is set.

        A bare key (F9) is convenient but Windows Terminal often swallows it
        before tmux sees it. A prefix binding (Ctrl-b then the key) always
        reaches tmux, so it's the reliable choice in WSL/Windows Terminal.
        """
        return [] if self.config.hotkey_prefix else ["-n"]

    def install(self) -> None:
        """Bind the hotkey in the running tmux server.

        `run-shell -b` runs voicecli in the background so tmux and your prompt
        stay responsive while recording/transcribing. Persist it across sessions
        by adding :meth:`config_line` to ~/.tmux.conf.
        """
        key = self.config.hotkey
        self._run(["tmux", "bind-key", *self._prefix_flag(), key,
                   "run-shell", "-b", self._shell_command()])
        how = f"the prefix then {key}" if self.config.hotkey_prefix else f"{key}"
        logger.info("Bound %s in the current tmux server. Press %s in any pane.", key, how)

    def uninstall(self) -> None:
        """Remove the binding from the running tmux server."""
        self._run(["tmux", "unbind-key", *self._prefix_flag(), self.config.hotkey])
        logger.info("Unbound %s", self.config.hotkey)

    def config_line(self) -> str:
        """The ~/.tmux.conf line that makes the binding permanent."""
        flag = " ".join(self._prefix_flag())
        prefix = f"{flag} " if flag else ""
        script = PROJECT_ROOT / "hotkey.sh"
        return (f'bind-key {prefix}{self.config.hotkey} '
                f'run-shell -b "{script}" "#{{pane_id}}"')

    @staticmethod
    def _run(cmd: list[str]) -> None:
        logger.debug("Running: %s", " ".join(repr(c) for c in cmd))
        subprocess.run(cmd, check=True)
