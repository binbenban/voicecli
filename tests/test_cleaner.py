"""Phase 4 + 7 checks: transcript cleanup and spoken aliases.

Run: .venv/bin/python -m unittest discover -s tests
Pure text-to-text, no model or mic — this is the whole point of keeping cleanup
separate from transcription.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleaner import Cleaner  # noqa: E402
from config import Config  # noqa: E402


def make_cleaner(**overrides) -> Cleaner:
    base = dict(
        cleanup_enabled=True,
        filler_words=["uh", "um", "like", "you know"],
        capitalize_sentences=True,
        ensure_end_punctuation=True,
        spoken_aliases={"slash review": "/review", "slash fix": "/fix"},
    )
    base.update(overrides)
    return Cleaner(Config(**base))


class CleanerTests(unittest.TestCase):
    def test_readme_example(self):
        c = make_cleaner()
        out = c.clean("uh explain maybe why this sql query is slow")
        self.assertEqual(out, "Explain maybe why this sql query is slow.")

    def test_filler_removed_and_capitalized_and_punctuated(self):
        c = make_cleaner()
        self.assertEqual(c.clean("um hello there"), "Hello there.")

    def test_multi_sentence_capitalization(self):
        c = make_cleaner()
        self.assertEqual(c.clean("first thing. second thing"),
                         "First thing. Second thing.")

    def test_alias_expands_before_capitalization(self):
        c = make_cleaner()
        # "/review" must stay lowercase-slash, not become "/Review".
        self.assertEqual(c.clean("slash review this function"),
                         "/review this function.")

    def test_longest_alias_wins(self):
        c = make_cleaner(spoken_aliases={"slash": "/", "slash review": "/review"})
        self.assertEqual(c.clean("slash review"), "/review.")

    def test_disabled_only_strips(self):
        c = make_cleaner(cleanup_enabled=False)
        self.assertEqual(c.clean("  uh hello  "), "uh hello")

    def test_no_double_end_punctuation(self):
        c = make_cleaner()
        self.assertEqual(c.clean("done!"), "Done!")

    def test_space_before_punctuation_fixed(self):
        c = make_cleaner()
        self.assertEqual(c.clean("hello , world"), "Hello, world.")


if __name__ == "__main__":
    unittest.main()
