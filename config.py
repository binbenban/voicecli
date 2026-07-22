"""Configuration loading for voicecli.

A single :class:`Config` dataclass holds all tunables. Values come from a YAML
file (``config.yaml`` by default); anything absent falls back to the dataclass
default. This keeps the schema in one place (the dataclass) while letting users
override without touching code.

Design notes
------------
* Dataclass, not a dict: attribute access, type hints, and defaults in one spot.
* Unknown YAML keys are ignored rather than fatal, so commented-out future-phase
  options (model, hotkey, ...) can live in config.yaml without breaking Phase 1.
* No global singleton. Callers construct a Config and pass it down (dependency
  injection). Tests build their own in-memory Config with no file at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Project root = directory this file lives in. Relative paths in config resolve
# against it so the tool works regardless of the caller's cwd.
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# Per-pane PID file so multiple panes can record independently. The pane_id
# (e.g. "%5" or "mysess:0.1") is embedded in the filename. "global" is used
# when no pane context is available (e.g. --file or --print mode).
def record_pidfile(pane_id: str = "global") -> Path:
    safe = pane_id.replace(":", "_").replace(".", "_")
    return PROJECT_ROOT / f".voicecli-rec-{safe}.pid"

# Unix socket for the warm-model transcription daemon (Phase 9). The daemon
# keeps the Whisper model resident so each dictation skips the multi-second
# model load; the per-press client connects here to transcribe.
DAEMON_SOCKET = PROJECT_ROOT / ".voicecli-daemon.sock"


@dataclass
class Config:
    """All voicecli settings. One field per config.yaml key.

    Phase 1 uses only the audio fields; later phases add their own without
    changing how config is loaded.
    """

    # --- Audio / recording (Phase 1) ---
    sample_rate: int = 16000
    channels: int = 1
    audio_format: str = "wav"
    recordings_directory: str = "recordings"
    sox_input_device: str = "default"

    # --- Silence auto-stop (Phase 2) ---
    stop_on_silence: bool = True
    silence_threshold: str = "3%"
    silence_duration: str = "1.5"
    start_threshold: str = "3%"
    start_duration: str = "0.1"
    max_duration: str = "30"
    mic_warmup: float = 0.5  # seconds to wait for SoX to open the mic before "listening"

    # --- Transcription / Whisper (Phase 3) ---
    model: str = "small"
    language: str = "en"
    device: str = "cpu"
    compute_type: str = "int8"
    models_directory: str = "models"
    beam_size: int = 5

    # --- Cleanup (Phase 4) ---
    cleanup_enabled: bool = True
    filler_words: list[str] = field(default_factory=list)
    capitalize_sentences: bool = True
    ensure_end_punctuation: bool = True

    # --- Spoken command aliases (Phase 7) ---
    spoken_aliases: dict[str, str] = field(default_factory=dict)

    # --- Output / terminal injection (Phase 5) ---
    output_mode: str = "auto"
    tmux_target: str = ""
    tmux_send_enter: bool = False
    herdr_target: str = ""  # herdr pane id (e.g. "w1:p5"); empty = resolve at runtime

    # --- Hotkey / push-to-talk (Phase 6) ---
    hotkey: str = "F9"
    hotkey_prefix: bool = False  # True = prefix key (Ctrl-b <key>); survives terminals that eat bare keys

    # --- Warm-model daemon (Phase 9) ---
    use_daemon: bool = True          # Keep the model resident so each press skips the model load.
    daemon_idle_timeout: float = 900.0  # Daemon exits after this many idle seconds (frees RAM).

    # --- Recording management ---
    max_recordings: int = 0          # 0 = unlimited; oldest files pruned when exceeded.

    @property
    def models_path(self) -> Path:
        """Absolute path to the Whisper model cache, created on demand."""
        p = Path(self.models_directory)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def recordings_path(self) -> Path:
        """Absolute path to the recordings directory, created on demand."""
        p = Path(self.recordings_directory)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    def validate(self) -> list[str]:
        """Return a list of validation error strings (empty = valid)."""
        errors = []
        if self.sample_rate <= 0:
            errors.append(f"sample_rate must be positive, got {self.sample_rate}")
        if self.channels not in (1, 2):
            errors.append(f"channels must be 1 or 2, got {self.channels}")
        if self.beam_size < 1:
            errors.append(f"beam_size must be >= 1, got {self.beam_size}")
        try:
            if float(self.max_duration) <= 0:
                errors.append(f"max_duration must be positive, got {self.max_duration}")
        except (ValueError, TypeError):
            errors.append(f"max_duration must be a number, got {self.max_duration!r}")
        try:
            if float(self.silence_duration) <= 0:
                errors.append(f"silence_duration must be positive, got {self.silence_duration}")
        except (ValueError, TypeError):
            errors.append(f"silence_duration must be a number, got {self.silence_duration!r}")
        valid_modes = {"auto", "tmux", "osc52", "clipboard", "stdout"}
        if self.output_mode not in valid_modes:
            errors.append(f"output_mode must be one of {sorted(valid_modes)}, got {self.output_mode!r}")
        if self.device not in ("cpu", "cuda"):
            errors.append(f"device must be cpu or cuda, got {self.device!r}")
        if self.max_recordings < 0:
            errors.append(f"max_recordings must be >= 0, got {self.max_recordings}")
        if self.mic_warmup < 0:
            errors.append(f"mic_warmup must be >= 0, got {self.mic_warmup}")
        return errors


def load_config(path: Path | str | None = None) -> Config:
    """Load a :class:`Config` from YAML, falling back to defaults.

    Args:
        path: Config file path. ``None`` uses ``config.yaml`` next to this
            module. A missing file is not an error — defaults are used.

    Returns:
        A populated Config. Unknown keys in the file are logged and skipped.
    """
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH

    data: dict[str, Any] = {}
    if cfg_path.exists():
        loaded = yaml.safe_load(cfg_path.read_text()) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{cfg_path} must contain a YAML mapping, got {type(loaded).__name__}")
        data = loaded
        logger.debug("Loaded config from %s", cfg_path)
    else:
        logger.warning("Config %s not found; using defaults", cfg_path)

    known = {f.name for f in fields(Config)}
    kwargs = {}
    for key, value in data.items():
        if key in known:
            kwargs[key] = value
        else:
            logger.debug("Ignoring unknown config key %r", key)

    cfg = Config(**kwargs)
    errors = cfg.validate()
    if errors:
        raise ValueError("Invalid config:\n  " + "\n  ".join(errors))
    return cfg
