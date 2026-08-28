#!/usr/bin/env python3
"""Guards that saving a practice answer does not force the page to the top."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PracticeScrollTest(unittest.TestCase):
    def test_save_keeps_scroll_and_overlay_does_not_reset_it(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        page_js = (ROOT / "static" / "practice-page.js").read_text(encoding="utf-8")

        self.assertIn("restorePracticeScroll", app_js)
        self.assertIn("keepScroll: true", app_js)
        self.assertIn('focusRole: "given"', app_js)
        self.assertIn('focusRole: "key"', app_js)
        self.assertIn("preventScroll", app_js)
        self.assertIn("cardTop", app_js)
        self.assertIn("applyCopiedTable", app_js)
        self.assertIn("bumpSaveEpoch", app_js)
        self.assertIn("keepRicher", app_js)
        self.assertIn("syncStartDateWeekday", app_js)
        self.assertIn("applyCopiedRow", app_js)
        self.assertIn("row-copy-btn", app_js)

        self.assertNotIn("scrollTop = 0", page_js)
        self.assertNotIn("view.scrollTop = 0", page_js)
        self.assertNotIn("subtree: true", page_js)


if __name__ == "__main__":
    unittest.main()
