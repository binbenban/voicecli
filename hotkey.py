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
import os
import shutil
import subprocess
from dataclasses import dataclass

from config import Config, PROJECT_ROOT

logger = logging.getLogger(__name__)


def _in_herdr() -> bool:
    """True when running inside a herdr pane (its own multiplexer, not tmux)."""
    return bool(os.environ.get("HERDR_ENV")) and shutil.which("herdr") is not None


@dataclass
class HotkeyInstaller:
    """Installs/removes the multiplexer keybinding that triggers dictation.

    Two backends: tmux (live `bind-key`) and herdr (a `[[keys.command]]` block
    in config.toml — herdr has no live-bind socket command, so install() emits
    the block for the user to paste, then reloads).
    """

    config: Config

    def __post_init__(self) -> None:
        if _in_herdr():
            return  # herdr backend, tmux not required
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

    # --- herdr backend -------------------------------------------------
    def _herdr_key(self) -> str:
        """herdr binding key, e.g. "prefix+t". hotkey_prefix maps to the
        `prefix+` chord; a bare key is used verbatim."""
        return f"prefix+{self.config.hotkey}" if self.config.hotkey_prefix else self.config.hotkey

    def _herdr_block(self) -> str:
        """The config.toml `[[keys.command]]` block that binds the hotkey."""
        script = PROJECT_ROOT / "hotkey.sh"
        return ('[[keys.command]]\n'
                f'key = "{self._herdr_key()}"\n'
                'type = "shell"\n'
                f'command = "{script}"')

    @staticmethod
    def _herdr_config_path():
        import os
        from pathlib import Path
        override = os.environ.get("HERDR_CONFIG_PATH")
        if override:
            return Path(override)
        return Path.home() / ".config" / "herdr" / "config.toml"

    def _herdr_write_config(self) -> None:
        """Append the keybinding block to config.toml, idempotently.

        Skips if a [[keys.command]] already points at our hotkey.sh — re-running
        setup won't stack duplicate bindings.
        """
        path = self._herdr_config_path()
        script = str(PROJECT_ROOT / "hotkey.sh")
        existing = path.read_text() if path.exists() else ""
        if script in existing:
            logger.info("herdr binding already present in %s", path)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        sep = "" if existing.endswith("\n\n") or not existing else ("\n" if existing.endswith("\n") else "\n\n")
        path.write_text(existing + sep + self._herdr_block() + "\n")
        logger.info("Added herdr binding to %s", path)

    def install(self) -> None:
        """Bind the hotkey in the running multiplexer.

        tmux: live `bind-key` (`run-shell -b` keeps the prompt responsive).
        herdr: bindings live in config.toml, so print the block and reload the
        server — the block must be added to config.toml to persist.
        """
        if _in_herdr():
            self._herdr_write_config()
            subprocess.run(["herdr", "server", "reload-config"], check=False)
            logger.info("Bound %s in herdr. Press it in any pane.", self._herdr_key())
            return
        key = self.config.hotkey
        self._run(["tmux", "bind-key", *self._prefix_flag(), key,
                   "run-shell", "-b", self._shell_command()])
        how = f"the prefix then {key}" if self.config.hotkey_prefix else f"{key}"
        logger.info("Bound %s in the current tmux server. Press %s in any pane.", key, how)

    def uninstall(self) -> None:
        """Remove the binding from the running multiplexer."""
        if _in_herdr():
            print(f"Remove the [[keys.command]] block for key "
                  f'"{self._herdr_key()}" from ~/.config/herdr/config.toml, '
                  "then run: herdr server reload-config")
            return
        self._run(["tmux", "unbind-key", *self._prefix_flag(), self.config.hotkey])
        logger.info("Unbound %s", self.config.hotkey)

    def config_line(self) -> str:
        """The config line/block that makes the binding permanent."""
        if _in_herdr():
            return self._herdr_block()
        flag = " ".join(self._prefix_flag())
        prefix = f"{flag} " if flag else ""
        script = PROJECT_ROOT / "hotkey.sh"
        return (f'bind-key {prefix}{self.config.hotkey} '
                f'run-shell -b "{script}" "#{{pane_id}}"')

    @staticmethod
    def _run(cmd: list[str]) -> None:
        logger.debug("Running: %s", " ".join(repr(c) for c in cmd))
        subprocess.run(cmd, check=True)
