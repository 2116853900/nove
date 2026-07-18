from __future__ import annotations

import unittest

from src.web.chat.helpers import parse_dialogue_responses


class DialogueJsonParsingTests(unittest.TestCase):
    def test_parse_dialogue_responses_accepts_literal_newlines_in_messages(self) -> None:
        content = """[
  {
    "speaker": "祥子",
    "message": "你好
这是第二行"
  }
]"""
        responses = parse_dialogue_responses(content, ["祥子", "小福子"])
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["speaker"], "祥子")
        self.assertIn("第二行", responses[0]["message"])


if __name__ == "__main__":
    unittest.main()
