import unittest

from utils import trim_text_to_token_budget


class FakeTokenizer:
    def __call__(self, text, add_special_tokens=False):
        del add_special_tokens
        return {"input_ids": text.split()}

    def decode(self, ids, skip_special_tokens=False):
        del skip_special_tokens
        return " ".join(ids)


class ContextBudgetTests(unittest.TestCase):
    def test_negative_budget_keeps_text(self):
        self.assertEqual(trim_text_to_token_budget(None, "alpha beta", -1), "alpha beta")

    def test_tail_budget_uses_tokenizer(self):
        text = "alpha beta gamma delta"
        self.assertEqual(
            trim_text_to_token_budget(FakeTokenizer(), text, 2, keep="tail"),
            "gamma delta",
        )

    def test_head_budget_uses_tokenizer(self):
        text = "alpha beta gamma delta"
        self.assertEqual(
            trim_text_to_token_budget(FakeTokenizer(), text, 2, keep="head"),
            "alpha beta",
        )


if __name__ == "__main__":
    unittest.main()
