"""Telegram news posts and goal clips for the soccer news account."""
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
PROMO = re.compile(r"\b(?:sponsored|casino|betting|promo code|sportsbook)\b", re.I)
NOT_GOAL = re.compile(
    r"\b(?:full time|half time|"
    r"goal kick|penalty shootout|penalty saved|missed|red card)\b", re.I
)
DISALLOWED = re.compile(r"\b(?:disallowed|ruled out|no goal|(?:flagged|given|for) offside)\b", re.I)
NAME = r"[^\W\d_][^\W\d_’'–-]*(?:[’'–-][^\W\d_]+)*"
SCORER = (
    re.compile(rf"^({NAME}(?:\s+{NAME}){{0,3}})\s+(?:scores?\b|equalis\w*\b|equaliz\w*\b)", re.I),
    re.compile(rf"^({NAME}(?:\s+{NAME}){{0,3}})[’']s\s+goal\b", re.I),
    re.compile(rf"^disallowed goal (?:for|by|from)\s+({NAME}(?:\s+{NAME}){{0,3}})$", re.I),
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
    disallowed: bool = False


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
    disallowed = bool(DISALLOWED.search(entry.text))
    lines = re.split(r"\n|\s+[|l]\s+", entry.text)
    if disallowed:
        scorer = None
        for line in lines:
            cleaned = clean(line)
            for pattern in SCORER:
                if match := pattern.match(cleaned):
                    scorer = match[1]
                    break
            if scorer:
                break
        reason = " | Offside" if re.search(r"\boffside\b", entry.text, re.I) else ""
        label = f"⚽ DISALLOWED GOAL | {scorer}" if scorer else "⚽ DISALLOWED GOAL"
        # The feed may show the overturned score. Never present it as the match score.
        event = hashlib.sha256(entry.url.encode()).hexdigest()[:22]
        return Goal(f"disallowed-{event}", label + reason, entry, disallowed=True)
    for line in lines:
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


def collect(config, now, news_max_age):
    channels = config["goals"] + config["news"]

    def fetch(channel):
        try:
            return list(entries(channel)), None
        except (OSError, ValueError) as error:
            return [], type(error).__name__

    goals, news, report = [], [], {}
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
                recent = [post for post in posts if 0 <= now - post.published <= news_max_age]
                news.extend((channel, post) for post in recent)
                report[channel] = {"posts": len(posts), "fresh_news_posts": len(recent)}
    return goals, news, report
