import io
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

import news_copy


class CopyTests(unittest.TestCase):
    def render(self, lead, question, source="BBC Sport"):
        payload = {"candidates": [{"content": {"parts": [
            {"text": json.dumps({"lead": lead, "question": question})}
        ]}}]}
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), \
             patch.object(news_copy, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as call:
            post = news_copy.draft("City beat United 2-1", "City won at home.", source)
        self.assertEqual(call.call_args.args[0].get_header("X-goog-api-key"), "test")
        return post

    def test_rewritten_post_has_no_source_link(self):
        self.assertEqual(
            self.render("United fall 2-1 to City", "Did City win it tactically or did United give it away?"),
            "United fall 2-1 to City\n\nDid City win it tactically or did United give it away?\n\n(Source: BBC Sport)",
        )

    def test_telegram_copy_omits_channel_credit_and_link(self):
        self.assertEqual(
            self.render("United fall 2-1 to City", "Did City get the tactics right?",
                        "Telegram / LiveFootballEA"),
            "United fall 2-1 to City\n\nDid City get the tactics right?",
        )
        self.assertIsNone(self.render("United fall to City, via LiveFootballEA", "",
                                      "Telegram / LiveFootballEA"))
        self.assertIsNone(self.render("United fall to City, see t.me/channel/2", "",
                                      "Telegram / LiveFootballEA"))

    def test_rejects_copied_headlines_links_and_invented_numbers(self):
        self.assertIsNone(self.render("City beat United 2-1!", "Right result?"))
        self.assertIsNone(self.render("United fall to City", "See https://example.com?"))
        self.assertIsNone(self.render("United fall 3-1 to City", "Right result?"))

    def test_quote_requires_a_recognized_post_and_new_source_evidence(self):
        prior = {"123": {"headline": "United open talks for Garcia",
                         "post": "United have opened talks for Garcia."}}
        copy = {"lead": "Garcia signs for United on a five-year deal.",
                "question": "Is he worth building around?", "quote_id": "123",
                "new_fact": "agreed a five-year deal"}

        def render():
            payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(copy)}]}}]}
            with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), \
                 patch.object(news_copy, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
                return news_copy.draft_update("United confirm Garcia transfer",
                                              "Garcia agreed a five-year deal.", "BBC Sport", prior)

        self.assertEqual(render()[1], "123")
        copy["new_fact"] = "passed his medical"
        self.assertIsNone(render()[1])
        copy.update(quote_id="999", new_fact="agreed a five-year deal")
        self.assertIsNone(render()[1])
        copy["quote_id"] = "123"
        prior["123"]["post"] = "Garcia agreed a five-year deal."
        self.assertIsNone(render()[1])

    def test_rate_limit_skips(self):
        failure = HTTPError("", 429, "rate limited", {}, None)
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), patch.object(
            news_copy, "urlopen", side_effect=failure
        ):
            self.assertIsNone(news_copy.draft("City beat United 2-1", "", "BBC Sport"))
