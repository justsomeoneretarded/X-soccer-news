"""Telegram signals and goal clips for the soccer news account."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
import unicodedata
from urllib.parse import quote

from bs4 import BeautifulSoup

import app
import media


GOAL_MAX_AGE = 45 * 60
SIGNAL_MAX_AGE = 2 * 3600
PROMO = re.compile(r"\b(?:sponsored|casino|betting|promo code|sportsbook)\b", re.I)
NOT_GOAL = re.compile(
    r"\b(?:offside|disallowed|ruled out|no goal|full time|half time|"
    r"goal kick|penalty shootout|penalty saved|missed|red card)\b", re.I
)
GOAL_LANGUAGE = re.compile(r"\b(?:goals?|scores?|equalis\w+|equaliz\w+|seals? the comeback)\b", re.I)
SCORE = re.compile(r"^(.+?)\s+\[?(\d{1,2})\s*[-–:]\s*(\d{1,2})\]?\s+(.+)$")


@dataclass(frozen=True)
class Entry:
    url: str
    published: float
    text: str
    video: str | None


@dataclass(frozen=True)
class Goal:
    identity: str
    caption: str
    entry: Entry


def entries(channel):
    page = app.fetch(f"https://t.me/s/{quote(channel, safe='')}")
    messages = BeautifulSoup(page, "html.parser").select(".tgme_widget_message[data-post]")
    if not messages:
        raise ValueError("No public preview posts")
    for message in messages:
        post = message["data-post"]
        if not re.fullmatch(re.escape(channel) + r"/\d+", post, re.I):
            continue
        timestamp = message.select_one("time[datetime]")
        body = message.select_one(".tgme_widget_message_text")
        if not timestamp or not body:
            continue
        try:
            date = datetime.fromisoformat(timestamp["datetime"])
        except ValueError:
            continue
        if date.tzinfo is None:
            continue
        for br in body.select("br"):
            br.replace_with("\n")
        text = body.get_text(strip=False).strip()
        if not text or PROMO.search(text):
            continue
        video_tag = message.select_one("video[src], video source[src]")
        url = video_tag.get("src") if video_tag else None
        yield Entry(f"https://t.me/{post}", date.timestamp(), text,
                    url if media.media_allowed(url) else None)


def clean(line):
    # Strip flag glyphs and variation selectors while keeping accented names.
    return " ".join("".join(c for c in line if unicodedata.category(c)[:1] in "LN"
                            or c.isspace() or c in "-–:'’[]()").split())


def goal(entry):
    if not entry.video or NOT_GOAL.search(entry.text) or not GOAL_LANGUAGE.search(entry.text):
        return None
    for line in re.split(r"\n|\s+[|l]\s+", entry.text):
        match = SCORE.fullmatch(re.sub(r"^Goal\s+", "", clean(line), flags=re.I))
        if not match:
            continue
        first, left, right, second = match.groups()
        teams = (first, second)
        if (any(not 1 <= len(name) <= 40 or re.search(r"\d|\b(?:scores?|goal)\b", name, re.I)
                for name in teams)
                or int(left) + int(right) == 0):
            continue
        def key(name):
            return "".join(c for c in unicodedata.normalize("NFKD", name.casefold()) if c.isalnum())
        pair = sorted(((key(first), int(left)), (key(second), int(right))))
        event = hashlib.sha256(repr(pair).encode()).hexdigest()[:22]
        return Goal(f"goal-{event}", f"⚽ GOAL | {first} {int(left)}–{int(right)} {second}", entry)
    return None


def collect(config, now):
    channels = config["goals"] + config["news"]

    def fetch(channel):
        try:
            return list(entries(channel)), None
        except (OSError, ValueError) as error:
            return [], type(error).__name__

    goals, signals, report = [], [], {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for channel, (posts, error) in zip(channels, pool.map(fetch, channels)):
            if error:
                report[channel] = {"error": error}
                continue
            if channel in config["goals"]:
                clips = [clip for post in posts if 0 <= now - post.published <= GOAL_MAX_AGE
                         if (clip := goal(post))]
                goals.extend(clips)
                report[channel] = {"posts": len(posts), "fresh_goal_clips": len(clips)}
            else:
                recent = [post.text for post in posts if 0 <= now - post.published <= SIGNAL_MAX_AGE]
                signals.extend(recent)
                report[channel] = {"posts": len(posts), "fresh_news_signals": len(recent)}
    return goals, signals, report
