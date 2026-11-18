# X Soccer News

An English-language soccer news poster for a global audience. It reads the
public football RSS feeds from BBC Sport, The Guardian and Sky Sports. Each run
previews or publishes one eligible headline with the publisher name and article URL.

- Uses the publisher's headline and publication time. Items over 90 minutes
  old, future-dated items, and apparent gossip, betting, opinion or watch
  guides are skipped. The headline filters are heuristic.
- Ranks by recency, with a small boost for apparent results, signings and
  announcements. Some stories will appear later than events because the bot
  depends on publishers' RSS update times.
- Skips previously attempted URLs and similar recent headlines. This is
  headline-based deduplication, so feeds can still describe the same event
  in very different words.
- Reserves a story in this repo's own `autopost-state` branch before sending.
  An uncertain send is preserved in history and that headline is never retried.

## Preview and go live

1. Open **Actions → Soccer news → Run workflow** on main. Preview needs no
   credentials. Check **Create isolated posting history with a preview** once
   before the first live run. The preview may report that no headline qualifies.
2. Set the **news account's** `TWEETKIT_COOKIE` under repository **Settings →
   Secrets and variables → Actions**. The pinned TweetKit adapter uses an
   unofficial X session and can stop working if the session expires.
3. Run with **Publish one eligible headline to X** checked and confirm the
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

The local command previews without an X session or installed dependencies.
Live access and scheduling require account setup.
