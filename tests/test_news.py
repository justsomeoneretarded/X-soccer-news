from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import app
import automation
import news_worker as news


class NewsTests(unittest.TestCase):
    now = datetime(2026, 11, 18, tzinfo=timezone.utc).timestamp()
    source = {"name": "Example Sport", "hosts": ["example.org"], "priority": 1, "path_prefix": "/soccer/"}

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db = patch.object(app, "DB", Path(directory.name) / "news.db")
        db.start()
        self.addCleanup(db.stop)
        clock = patch.object(app, "now", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def test_feed_rejects_stale_future_untrusted_and_speculative_items(self):
        def item(title, url, age):
            return (f"<item><title>{title}</title><link>{url}</link>"
                    f"<pubDate>{formatdate(self.now-age, usegmt=True)}</pubDate></item>")
        xml = "<rss><channel>" + "".join([
            item("Club confirms new coach", "https://www.example.org/soccer/coach?utm_source=rss", 120),
            item("Old result", "https://www.example.org/soccer/old", news.MAX_AGE + 1),
            item("Future result", "https://www.example.org/soccer/future", -60),
            item("Club signs striker", "https://example.org.bad.example/soccer/result", 100),
            item("England beats Australia", "https://www.example.org/cricket/live", 90),
            item("Player back to training", "https://www.example.org/soccer/live-blog/transfer-gossip", 70),
            item("Club reportedly signs striker", "https://www.example.org/soccer/rumour", 100),
        ]) + "</channel></rss>"
        [result] = list(news.parse_feed(xml, self.source, self.now))
        self.assertEqual(result.url, "https://www.example.org/soccer/coach")
        self.assertTrue(result.post.startswith("Club confirms new coach\n\nExample Sport"))

    def story(self, title="Club confirms their new head coach", path="coach"):
        return news.Story(title, f"https://example.org/{path}", "Example Sport", self.now - 60, 1)

    def test_preview_does_not_contact_x_or_reserve(self):
        with patch.object(news, "collect", return_value=([self.story()], {"source": {"eligible": 1}})), \
             patch.object(automation, "authorization") as auth, patch.object(automation, "send") as send:
            result = news.run(None)
        self.assertEqual(result["publishing"], "preview")
        auth.assert_not_called()
        send.assert_not_called()
        with automation.ledger() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM publications").fetchone()[0], 0)

    def test_reserved_story_and_near_duplicate_do_not_retry(self):
        results = [([self.story()], {"source": {"eligible": 1}}),
                   ([self.story("Club confirms new head coach", "other")], {"source": {"eligible": 1}})]
        state = Mock()

        def timeout(_):
            state.checkpoint.assert_called_once()
            with automation.ledger() as connection:
                self.assertEqual(connection.execute("SELECT state FROM publications").fetchone()[0], "uncertain")
            raise TimeoutError

        with patch.object(news, "collect", side_effect=results), patch.object(automation, "authorization"), \
             patch.object(automation, "send", side_effect=timeout) as send:
            self.assertFalse(news.run(state, live=True)["ok"])
            self.assertEqual(news.run(state, live=True)["publishing"], "no fresh eligible headline")
        send.assert_called_once()

    def test_changed_score_stays_distinct(self):
        self.assertFalse(news.same_headline("United beats City 2-1 in cup", "United beats City 3-1 in cup"))


if __name__ == "__main__":
    unittest.main()
