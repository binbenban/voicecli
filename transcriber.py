"""Speech-to-text via Faster-Whisper (Phase 3).

Faster-Whisper runs OpenAI's Whisper models on CTranslate2 — 4x faster than the
reference implementation with lower memory, and it runs on plain CPU. That
matters here: WSL usually has no GPU passthrough, so int8-on-CPU is the default
path and a GPU is an opt-in bonus.

Model download is automatic: the first transcription for a given model name
fetches the weights from Hugging Face into ``models_directory`` and caches them.

The model is loaded lazily and reused. Loading takes a few seconds, so we do it
once per process, not per recording.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from config import Config, PROJECT_ROOT

logger = logging.getLogger(__name__)


@dataclass
class Transcriber:
    """Transcribes a WAV file to text using a Faster-Whisper model.

    The model is loaded on first use (:meth:`_ensure_model`) and cached on the
    instance, so a long-running process pays the load cost once.
    """

    config: Config
    _model: object | None = field(default=None, init=False, repr=False)

    def _ensure_model(self) -> object:
        """Load the Whisper model once, caching it on the instance."""
        if self._model is not None:
            return self._model

        # HF's xet CDN backend returns 403 for these model blobs, hanging the
        # download for minutes before failing. Force the classic HTTP path.
        # ponytail: env flag, not a config knob — it's a workaround for an HF bug.
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

        # Imported lazily so `python main.py` (Phase 1/2) works without the
        # faster-whisper dependency installed.
        from faster_whisper import WhisperModel

        c = self.config
        # A model name ("base") downloads from HF; a path to a local dir loads
        # offline. Resolve a relative local dir against PROJECT_ROOT so it works
        # regardless of the caller's cwd (the hotkey runs from the pane's cwd).
        model = c.model
        local = PROJECT_ROOT / model
        if local.is_dir():
            model = str(local)
        logger.info(
            "Loading Whisper model %r (device=%s, compute_type=%s)",
            model, c.device, c.compute_type,
        )
        self._model = WhisperModel(
            model,
            device=c.device,
            compute_type=c.compute_type,
            download_root=str(c.models_path),
        )
        return self._model

    def transcribe(self, audio_path: Path) -> str:
        """Transcribe an audio file to plain text.

        Args:
            audio_path: Path to a WAV (or any format ffmpeg/SoX can read).

        Returns:
            The joined transcript, stripped. Empty string if nothing was said.
        """
        if not audio_path.exists():
            raise FileNotFoundError(audio_path)

        model = self._ensure_model()
        c = self.config
        language = None if c.language in ("", "auto") else c.language

        logger.debug("Transcribing %s (language=%s)", audio_path, language or "auto")
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=c.beam_size,
        )
        # `segments` is a generator; consuming it runs the actual inference.
        text = " ".join(seg.text.strip() for seg in segments).strip()
        logger.info(
            "Transcribed %.1fs of %s audio -> %d chars",
            getattr(info, "duration", 0.0), getattr(info, "language", "?"), len(text),
        )
        return text
