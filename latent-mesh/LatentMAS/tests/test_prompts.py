import types
import unittest

from prompts import _context_window


class PromptContextWindowTests(unittest.TestCase):
    def test_negative_legacy_limit_keeps_context(self):
        args = types.SimpleNamespace(text_mas_context_length=-1)
        self.assertEqual(_context_window("abcdef", args), "abcdef")

    def test_positive_legacy_limit_caps_characters(self):
        args = types.SimpleNamespace(text_mas_context_length=3)
        self.assertEqual(_context_window("abcdef", args), "abc")


if __name__ == "__main__":
    unittest.main()
