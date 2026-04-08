import unittest

from app.search import parse_semantic_query


class SearchServiceTests(unittest.TestCase):
    def test_semantic_path_uses_bounded_timeout(self) -> None:
        result = parse_semantic_query("mesh intelligence")
        self.assertEqual(result["mode"], "semantic")
        self.assertLessEqual(result["timeout_ms"], 100)


if __name__ == "__main__":
    unittest.main()
