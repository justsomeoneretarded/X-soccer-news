"""Publish one fresh, attributed soccer headline per run."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import app
import automation
from actions_runner import GitState, StateError


MAX_AGE = 90 * 60
DUPLICATE_WINDOW = 12 * 3600
NON_NEWS = re.compile(r"\b(?:transfer talk|transfer rumours?|transfer rumors?|gossip|reportedly|sources?\s*:|exclusive|"
                      r"rumou?rs?|linked with|weighs? up|in talks|could sign|set to|"
                      r"predictions?|betting|odds|podcast|newsletter|watch live|minute-by-minute|"
                      r"how to watch|where to watch|player ratings|quiz(?:zes)?|opinion|long read|explained)\b|^from .+ to .+|\?$", re.I)
BREAKING = re.compile(r"\b(?:announc\w+|confirm\w+|signs?|appoint\w+|sack\w+|"
                      r"injur\w+|wins?|beats?|defeats?|qualif\w+|suspend\w+)\b", re.I)
STOP_WORDS = set("a an after at by for from in is of on the to with and as over".split())


@dataclass(frozen=True)
class Story:
    title: str
    url: str
    source: str
    published: float
    priority: int

    @property
    def identity(self):
        return hashlib.sha256(self.url.encode()).hexdigest()[:24]

    @property
    def post(self):
        return f"{self.title}\n\n{self.source}: {self.url}"


def canonical_url(url, hosts):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.netloc.lower() != host
                or not any(host == allowed or host.endswith("." + allowed) for allowed in hosts)
                or not parsed.path.strip("/")):
            return None
        query = urlencode(sorted((key, value) for key, value in parse_qsl(parsed.query)
                                 if not key.startswith(("utm_", "at_"))))
        return urlunsplit(("https", host, parsed.path.rstrip("/"), query, ""))
    except ValueError:
        return None


def parse_feed(data, source, now):
    rss = ElementTree.fromstring(data)
    if rss.find("channel") is None:
        raise ValueError("Expected an RSS channel")
    for item in rss.findall("./channel/item"):
        title = " ".join(html.unescape(item.findtext("title", "")).split())
        url = canonical_url(item.findtext("link", "").strip(), source["hosts"])
        try:
            date = parsedate_to_datetime(item.findtext("pubDate", ""))
            if date.tzinfo is None:
                continue
            published = date.timestamp()
        except (ValueError, TypeError, OverflowError):
            continue
        if (not url or not title or not 0 <= now - published <= MAX_AGE
                or not urlsplit(url).path.startswith(source["path_prefix"])
                or NON_NEWS.search(title) or any(c in title for c in ("@", "<", ">"))):
            continue
        # A conservative character budget allows for X's fixed-length URL handling.
        if 2 * len(title) + len(source["name"]) + 27 > 280:
            continue
        yield Story(title, url, source["name"], published, source["priority"])


def collect(sources, now):
    def read(source):
        try:
            return list(parse_feed(app.fetch(source["url"]), source, now)), None
        except Exception as error:
            return [], type(error).__name__

    stories, report = [], {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for source, (items, error) in zip(sources, pool.map(read, sources)):
            report[source["name"]] = {"error": error} if error else {"eligible": len(items)}
            stories.extend(items)
    return stories, report


def tokens(title):
    return set(re.findall(r"[^\W_]+", title.casefold())) - STOP_WORDS


def same_headline(first, second):
    left, right = tokens(first), tokens(second)
    # Keep changing scorelines and other numeric updates distinct.
    if {t for t in left if t.isdecimal()} != {t for t in right if t.isdecimal()}:
        return False
    return bool(left) and (left == right or (
        len(left & right) >= 4 and len(left & right) / len(left | right) >= 0.7))


def select(stories, connection, now):
    history = connection.execute("""
        SELECT s.url, s.title, p.attempted FROM stories s
        JOIN publications p ON p.story_id = s.id
    """).fetchall()
    def url_key(url):
        return url.removeprefix("https://").removeprefix("www.")

    seen_urls = {url_key(row["url"]) for row in history}
    recent_titles = [row["title"] for row in history if row["attempted"] >= now - DUPLICATE_WINDOW]
    eligible = (story for story in stories if 0 <= now - story.published <= MAX_AGE
                and url_key(story.url) not in seen_urls
                and not any(same_headline(story.title, title) for title in recent_titles))
    return max(eligible, key=lambda story: (
        story.published + (600 if BREAKING.search(story.title) else 0),
        story.priority, story.url), default=None)


def run(state, live=False):
    sources = json.loads((app.ROOT / "sources.json").read_text())
    stories, sources_report = collect(sources, app.now())
    report = {"sources": sources_report, "ok": any("eligible" in r for r in sources_report.values())}
    now = app.now()
    with automation.ledger() as connection:
        story = select(stories, connection, now)
        if story is None:
            return report | {"publishing": "no fresh eligible headline"}
        if not live:
            return report | {"publishing": "preview", "draft": story.post}
        automation.authorization()
        connection.execute("INSERT INTO stories VALUES(?,?,?,?,?,?,?,?)",
                           (story.identity, story.title, story.url, story.source, story.published, now, 0, "reserved"))
        connection.execute("INSERT INTO publications VALUES(?,?,?,NULL)", (story.identity, now, "uncertain"))
    state.checkpoint()
    try:
        post_id = automation.send(story.post)
    except Exception:
        return report | {"ok": False, "publishing": "outcome uncertain; headline reserved",
                         "source_url": story.url}
    with automation.ledger() as connection:
        connection.execute("UPDATE publications SET state='posted', post_id=? WHERE story_id=?",
                           (post_id, story.identity))
        connection.execute("UPDATE stories SET status='posted' WHERE id=?", (story.identity,))
    state.checkpoint()
    return report | {"publishing": "posted", "post_id": post_id, "source_url": story.url}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--initialize", action="store_true")
    args = parser.parse_args()
    try:
        state = GitState(app.ROOT, initialize=args.initialize) if args.live or args.initialize else None
        if state is None and os.environ.get("GITHUB_ACTIONS") == "true":
            try:
                state = GitState(app.ROOT)
            except StateError as error:
                if not str(error).startswith("No posting history branch."):
                    raise
        report = run(state, live=args.live)
    except (StateError, ValueError) as error:
        report = {"ok": False, "error": str(error)}
    Path("posting-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
