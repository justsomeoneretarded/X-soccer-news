from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import app
import automation
import news_worker
from telegram_news import Entry, goal


class GoalTests(unittest.TestCase):
    def entry(self, text, path="goalposten/1", age=60, video=True):
        return Entry("https://t.me/" + path, app.now() - age, text,
                     "https://cdn4.telesco.pe/clip.mp4" if video else None)

    def test_channel_formats_share_an_event_key(self):
        first = goal(self.entry("🚨 GOAL: Bruno Fernandes scores!\n🏴 Wales [0-1] Portugal 🇵🇹"))
        second = goal(self.entry("Goal l 🇵🇹 Portugal 1-0 Wales 🏴 l Bruno Fernandes"))
        self.assertEqual(first.identity, second.identity)
        self.assertEqual(first.caption, "⚽ GOAL | Wales 0–1 Portugal")

    def test_rejects_non_goal_or_missing_video(self):
        self.assertIsNone(goal(self.entry("Player ruled out of next match")))
        self.assertIsNone(goal(self.entry("Goal l Wales 0-1 Portugal", video=False)))
        self.assertIsNone(goal(self.entry("Goal for Portugal!")))

    def test_disallowed_goal_uses_the_scorer_and_omits_the_overturned_score(self):
        clip = goal(self.entry("🇳🇴 Haaland scores but has been ruled out for offside"))
        unnamed = goal(self.entry("Goal ruled out for offside\nWales 0-1 Portugal"))
        self.assertTrue(clip.disallowed)
        self.assertEqual(clip.caption, "⚽ DISALLOWED GOAL | Haaland | Offside")
        self.assertEqual(unnamed.caption, "⚽ DISALLOWED GOAL | Offside")

    def test_preview_is_read_only_and_live_deduplicates(self):
        clip = goal(self.entry("Goal l Wales 0-1 Portugal"))
        mirror = goal(self.entry("Goal l Portugal 1-0 Wales", "Goals_Channel/2"))
        overturned = goal(self.entry("Haaland's goal ruled out for offside", "Goals_Channel/4"))
        overturned_mirror = goal(self.entry("Haaland scores but it is disallowed", "Goals_Channel/5"))
        old = goal(self.entry("Goal l Wales 1-1 Portugal", "Goals_Channel/3", age=3600))
        with TemporaryDirectory() as directory, patch.object(app, "DB", Path(directory) / "news.db"):
            path = Path(directory) / "clip.mp4"
            path.write_bytes(b"clip")
            state = Mock()
            with patch.object(automation, "authorization"), patch.object(automation, "send", return_value="123") as send, \
                 patch.object(news_worker.media, "download_media", return_value=path) as download:
                result = news_worker.try_goal(state, [old, clip], {}, live=False)
                self.assertEqual(result["publishing"], "goal clip preview")
                download.assert_not_called()
                send.assert_not_called()
                result = news_worker.try_goal(state, [clip], {}, live=True)
                self.assertEqual(result["publishing"], "posted goal clip")
                send.assert_called_once_with(clip.caption, image_path=path)
                self.assertEqual(state.checkpoint.call_count, 2)
                self.assertIsNone(news_worker.try_goal(state, [mirror, old], {}, live=True))
                self.assertEqual(news_worker.try_goal(state, [overturned], {}, live=True)["publishing"],
                                 "posted goal clip")
                self.assertIsNone(news_worker.try_goal(state, [overturned_mirror], {}, live=True))
                self.assertEqual(send.call_count, 2)
