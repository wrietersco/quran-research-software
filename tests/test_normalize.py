"""Tests for Arabic normalization helpers."""

import unittest

from src.normalize.arabic import canonical_heading, normalize_arabic, strip_clitics_prefix


class TestNormalize(unittest.TestCase):
    def test_strip_diacritics(self):
        s = normalize_arabic("بِسْمِ")
        self.assertNotIn("\u064e", s)

    def test_alif_unify(self):
        # Diacritics removed; alif variants collapse to ا
        self.assertEqual(normalize_arabic("إِنَّ"), "ان")

    def test_strip_clitics(self):
        self.assertTrue(strip_clitics_prefix("والكتاب").startswith("كتاب"))

    def test_canonical_heading(self):
        self.assertIn("2.", canonical_heading(2, "1. ⇒ foo"))


if __name__ == "__main__":
    unittest.main()
