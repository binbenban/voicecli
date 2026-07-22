"""Push-to-talk hotkey via a herdr keybinding (Phase 6).

Why herdr and not a global hotkey?
    A true "hold F9 anywhere" hotkey needs OS-level keyboard access. Inside WSL
    that is unavailable: there is no /dev/input (no evdev), `legacy_tiocsti` is
    disabled (no TIOCSTI keystroke injection), and the physical keyboard is owned
    by Windows — the Linux side never even sees a key-release event. So a
    press-and-hold gesture cannot be observed here.

    herdr, however, sees every keypress inside its panes. Binding the hotkey in
    herdr gives a terminal-native push-to-talk: press the key, speak, and press
    again to stop. The transcript is injected straight back into the pane you
    pressed it in.

This module doesn't run a listener; it *installs* a herdr binding that shells
out to `hotkey.sh`. herdr has no live-bind socket command, so bindings live in
config.toml — install() appends a `[[keys.command]]` block, then reloads the
running server.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from config import Config, PROJECT_ROOT

logger = logging.getLogger(__name__)


@dataclass
class HotkeyInstaller:
    """Installs/removes the herdr keybinding that triggers dictation."""

    config: Config

    def _key(self) -> str:
        """herdr binding key, e.g. "prefix+t". hotkey_prefix maps to the
        `prefix+` chord; a bare key is used verbatim."""
        return f"prefix+{self.config.hotkey}" if self.config.hotkey_prefix else self.config.hotkey

    def _block(self) -> str:
        """The config.toml `[[keys.command]]` block that binds the hotkey."""
        script = PROJECT_ROOT / "hotkey.sh"
        return ('[[keys.command]]\n'
                f'key = "{self._key()}"\n'
                'type = "shell"\n'
                f'command = "{script}"')

    @staticmethod
    def _config_path() -> Path:
        override = os.environ.get("HERDR_CONFIG_PATH")
        if override:
            return Path(override)
        return Path.home() / ".config" / "herdr" / "config.toml"

    def _write_config(self) -> None:
        """Append the keybinding block to config.toml, idempotently.

        Skips if a [[keys.command]] already points at our hotkey.sh — re-running
        setup won't stack duplicate bindings.
        """
        path = self._config_path()
        script = str(PROJECT_ROOT / "hotkey.sh")
        existing = path.read_text() if path.exists() else ""
        if script in existing:
            logger.info("herdr binding already present in %s", path)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        sep = "" if existing.endswith("\n\n") or not existing else ("\n" if existing.endswith("\n") else "\n\n")
        path.write_text(existing + sep + self._block() + "\n")
        logger.info("Added herdr binding to %s", path)

    def install(self) -> None:
        """Bind the hotkey: write the config.toml block, then reload the server."""
        self._write_config()
        subprocess.run(["herdr", "server", "reload-config"], check=False)
        logger.info("Bound %s in herdr. Press it in any pane.", self._key())

    def uninstall(self) -> None:
        """Print how to remove the binding (herdr edits are manual + a reload)."""
        print(f"Remove the [[keys.command]] block for key "
              f'"{self._key()}" from {self._config_path()}, '
              "then run: herdr server reload-config")
