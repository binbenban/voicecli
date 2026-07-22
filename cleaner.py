"""Transcript cleanup (Phase 4) and spoken aliases (Phase 7).

Whisper returns readable text but not command-ready text: it keeps fillers
("uh", "um"), may lower-case the first word, and sometimes drops the trailing
period. This module turns a raw transcript into something you'd actually type.

Kept separate from the transcriber on purpose: cleanup is a text-to-text pass
with no model dependency, so it is trivially testable and could later be swapped
for an LLM-based cleaner without touching transcription.

Order of operations matters:
  1. spoken aliases  ("slash review" -> "/review") — before casing, so the
     literal replacement isn't capitalized.
  2. filler removal  (drop standalone "uh"/"um"/...).
  3. whitespace collapse.
  4. capitalization  (sentence starts).
  5. end punctuation (add a period if missing).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class Cleaner:
    """Rule-based transcript cleaner. Config-driven; no global state."""

    config: Config

    def clean(self, text: str) -> str:
        """Return a cleaned version of ``text`` per the configured rules."""
        if not self.config.cleanup_enabled:
            return text.strip()

        text = self._apply_aliases(text)
        text = self._remove_fillers(text)
        text = self._collapse_whitespace(text)
        if self.config.capitalize_sentences:
            text = self._capitalize_sentences(text)
        if self.config.ensure_end_punctuation:
            text = self._ensure_end_punctuation(text)
        return text

    # --- Phase 7: spoken aliases ---------------------------------------
    def _apply_aliases(self, text: str) -> str:
        """Replace spoken phrases with literals, longest phrase first.

        Matching is case-insensitive and on word boundaries so "slash review"
        maps to "/review" but "backslash reviews" is untouched. Longest-first
        prevents a short alias from eating part of a longer one.
        """
        for phrase in sorted(self.config.spoken_aliases, key=len, reverse=True):
            replacement = self.config.spoken_aliases[phrase]
            pattern = r"\b" + re.escape(phrase) + r"\b"
            text = re.sub(pattern, lambda _m: replacement, text, flags=re.IGNORECASE)
        return text

    # --- Phase 4: fillers ----------------------------------------------
    def _remove_fillers(self, text: str) -> str:
        """Drop configured filler words when they appear as standalone tokens."""
        for filler in self.config.filler_words:
            pattern = r"\b" + re.escape(filler) + r"\b"
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        return text

    @staticmethod
    def _collapse_whitespace(text: str) -> str:
        """Collapse runs of spaces/tabs and tidy space-before-punctuation.

        Newlines (e.g. from a "new line" alias) are preserved; only horizontal
        whitespace is collapsed.
        """
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s+([,.!?;:])", r"\1", text)  # no space before punctuation
        return text.strip()

    @staticmethod
    def _capitalize_sentences(text: str) -> str:
        """Uppercase the first alphabetic char of the string and after . ! ?"""
        def upper(match: re.Match[str]) -> str:
            return match.group(0).upper()

        # First letter of the whole string.
        text = re.sub(r"^\s*[a-z]", upper, text)
        # First letter after sentence-ending punctuation + space.
        text = re.sub(r"([.!?]\s+)([a-z])",
                      lambda m: m.group(1) + m.group(2).upper(), text)
        return text

    @staticmethod
    def _ensure_end_punctuation(text: str) -> str:
        """Add a period if the text is non-empty and lacks terminal punctuation."""
        if text and text[-1] not in ".!?":
            text += "."
        return text
