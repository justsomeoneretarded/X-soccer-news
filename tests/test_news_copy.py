import io
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

import news_copy


class CopyTests(unittest.TestCase):
    def render(self, lead, question):
        payload = {"candidates": [{"content": {"parts": [
            {"text": json.dumps({"lead": lead, "question": question})}
        ]}}]}
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), \
             patch.object(news_copy, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as call:
            post = news_copy.draft("City beat United 2-1", "City won at home.", "BBC Sport")
        self.assertEqual(call.call_args.args[0].get_header("X-goog-api-key"), "test")
        return post

    def test_rewritten_post_has_no_source_link(self):
        self.assertEqual(
            self.render("United fall 2-1 to City", "Did City win it tactically or did United give it away?"),
            "United fall 2-1 to City\n\nDid City win it tactically or did United give it away?\n\n(Source: BBC Sport)",
        )

    def test_rejects_copied_headlines_links_and_invented_numbers(self):
        self.assertIsNone(self.render("City beat United 2-1!", "Right result?"))
        self.assertIsNone(self.render("United fall to City", "See https://example.com?"))
        self.assertIsNone(self.render("United fall 3-1 to City", "Right result?"))

    def test_rate_limit_skips(self):
        failure = HTTPError("", 429, "rate limited", {}, None)
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), patch.object(
            news_copy, "urlopen", side_effect=failure
        ):
            self.assertIsNone(news_copy.draft("City beat United 2-1", "", "BBC Sport"))
