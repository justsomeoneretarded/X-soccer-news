# X Soccer News

An English-language soccer news poster for a global audience. It reads the
public football RSS feeds from BBC Sport, The Guardian and Sky Sports. Each run
previews or publishes one eligible story. Gemini rewrites the headline and
adds a sharp question when there is a real soccer debate to have. X posts
credit the publisher by name. The article URL remains in internal history.

- Uses the publisher's headline, RSS summary and publication time. Items over 90 minutes
  old, future-dated items, and apparent gossip, betting, opinion or watch
  guides are skipped. The headline filters are heuristic.
- Skips publication if Gemini is missing, rate-limited, or unable to return
  usable copy. The prompt calls for source-grounded rewrites. Output checks
  reject copied headlines, URLs and newly introduced numbers.
- Ranks by recency, with a small boost for apparent results, signings and
  announcements. Publisher names do not enter the ranking. Some stories
  will appear later than events because the bot depends on RSS update times.
- Skips previously attempted URLs and similar recent headlines. This is
  headline-based deduplication, so feeds can still describe the same event
  in very different words.
- Reserves a story in this repo's own `autopost-state` branch before sending.
  An uncertain send is preserved in history and that headline is never retried.

## Telegram and matchday goals

The channels in `telegram_sources.json` have two roles. The news channels
can give a small ranking boost to matching publisher headlines. Telegram
captions do not become standalone news claims.

`goalposten` and `Goals_Channel` supply goal clips. During active play, a
fresh, recognizable goal with a downloadable MP4 takes priority over a news
headline. The bot uses the source scoreline and posts the actual video with
a short caption. Clips must be posted to Telegram within the last 45 minutes.
The age check uses the Telegram timestamp, and the scoreline is taken from
the feed. Explicitly disallowed goals are labeled as such, with the scorer
when clear and without the overturned scoreline. The bot suppresses duplicate
counted match scores within six hours and identical videos for the same
outcome. An overturned goal can follow an earlier counted-goal clip.

Previews can show goal candidates without uploading video. Live runs can
post video, and `AUTO_PUBLISH` controls whether the scheduled runs are enabled.

## Preview and go live

1. Add `GEMINI_API_KEY` in **Settings → Secrets and variables → Actions**.
   You can use the same key as the meme account. Both workflows draw on
   that Google project's quota. `GEMINI_MODEL` is an optional Actions variable.
2. Open **Actions → Soccer news → Run workflow** on main. Preview needs no
   X session. Check **Create isolated posting history with a preview** once
   before the first live run. The preview may report that no headline qualifies.
3. Set the **news account's** `TWEETKIT_COOKIE` under repository **Settings →
   Secrets and variables → Actions**. The pinned TweetKit adapter uses an
   unofficial X session and can stop working if the session expires.
4. Run with **Publish one eligible item to X** checked and confirm the
   actual post on the account before enabling unattended dispatches.

The scheduled job stays disabled unless the repository Actions variable
`AUTO_PUBLISH` is set to `true`. Once enabled, GitHub requests a run every
10 minutes. GitHub can delay scheduled runs, and the 90-minute cutoff still
applies. An external scheduler can instead dispatch the workflow with
`{"ref":"main","inputs":{"live":true}}` using a token with Actions write
permission limited to this repository.

```sh
python -m unittest discover -s tests -v
python news_worker.py
```

Install the preview dependency with `python -m pip install -r requirements-preview.txt`.
The local command runs without an X session. Set
`GEMINI_API_KEY` in the environment to generate real preview copy.
Live access and scheduling require account setup.
