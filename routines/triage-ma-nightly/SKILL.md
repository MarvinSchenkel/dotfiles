---
name: triage-ma-nightly
description: Nightly scan of the Music Assistant nightly add-on logs for errors, event loop blocks and other bugs, reported inline in this thread
---

# Nightly MA log triage

You are the routine thread for this job. Each scheduled run arrives as a new turn in this thread.
Read `~/git/dotfiles/routines/state/triage-ma-nightly.json` first, then do the run below, then write
the state back and commit it in `~/git/dotfiles` as Marvin (marvinschenkel@gmail.com) with the
message `triage-ma-nightly: run <YYYY-MM-DD>`. Never push.

## Inputs

- Credentials: `source ~/.claude-teamB/ma-routines.env` gives `MA_URL` and `MA_TOKEN` (long-lived admin
  token named "Claude routine"). Never print the token or copy it into any file or report.
- Window: from `last_run_end` in the state file (fall back to 24 hours) until now.

## Collect

1. `diagnostics/get` over the MA websocket API. Lead with its `exceptions` ring buffer (type, count,
   first_seen, last_seen, origin, traceback): it spans a wider window than the log after a busy day.
   Also record `system.event_loop_lag_ms`, `system.memory.rss_mb` and `system.uptime_seconds`.
2. `logging/get` for the current session log. MA rotates the log on every start and on size, and the
   nightly add-on updates around 06:57 CEST, so this only covers the current session.
3. If the log does not reach back to `last_run_end`, SSH to the HA box (`ssh -i ~/.ssh/claude_ha_ed25519
   marvin@192.168.1.80`) and run `sudo docker logs --since <window start> addon_<music assistant slug>`.
   Record in the state file whether that worked so later runs know.

## Analyse

- Errors and tracebacks, grouped by fingerprint (exception type plus the top frame inside music_assistant).
- Event loop blocks and lag warnings that point at blocking code.
- Anything else that looks like a bug: repeated reconnect loops, stuck tasks, provider auth failures,
  player state flapping, memory growth versus the previous run.
- Compare every fingerprint against `known` in the state file. A fingerprint seen before gets its
  `seen` count bumped and keeps its first-seen date; a new one is marked new in the report.
- Severity: critical (crash, data loss, playback dead for everyone), high (a feature or provider broken
  for the whole instance), medium (one player or provider degraded, recoverable), low (noise, cosmetic,
  one-off). Health flat with nothing new is a valid outcome, say so.
- Only triage. No fixes, no PRs, no GitHub writes from this thread.

## Report

Render one page with `html_render` (preview with `html_preview` first). Use T3's CSS variables
(`--foreground`, `--muted-foreground`, `--border`, `--card`, `--destructive`, `--warning`, `--success`,
`--radius`, `--font-sans`, `--font-mono`), no page background, fluid width, no outer card. Layout, top
to bottom:

1. Title line with the window covered and the add-on version.
2. Health tiles: exceptions, event loop lag p95, RSS, uptime, restarts, each coloured good or warn.
3. One verdict sentence.
4. Findings grouped by severity, each as a `<details>` block whose summary shows the id (`f1`, `f2` ...),
   a short title, the fingerprint count and a "new" badge when applicable. The body holds where it
   happened, the first and last timestamp, the relevant log excerpt in a `<pre>`, and your read on the
   likely cause with the server file and line if you can tell.
5. A footer line: "Reply `fix <id>` to start a fix session, `mute <id>` to stop reporting it."

Keep the build script that produces the page at `~/git/dotfiles/routines/triage-ma-nightly/build.py`
once it works, and reuse it on later runs so the layout stays stable. The script takes the run's
findings JSON and writes the HTML.

After the render, end the turn with a chat summary of at most four sentences: what is new, what got
worse, what you recommend Marvin looks at first.

## Replies

- `fix <id>`: launch a thread with `t3_thread_launch` in the server repo on a new worktree branch
  `fix/<short-slug>` off `dev`, title "Fix: <finding title>", message containing the finding details,
  the log excerpt and the instruction to start with the gogogo skill. Link the thread in your reply.
- `mute <id>`: add the fingerprint to `muted` in the state file and commit.
- Anything else: answer from the data you already have, re-query MA if needed.

## State file shape

```json
{
  "thread_id": "<this thread's id>",
  "last_run_end": "2026-10-21T05:10:00+02:00",
  "last_run_summary": "one sentence",
  "known": { "<fingerprint>": { "title": "", "severity": "", "first_seen": "", "seen": 1 } },
  "muted": [],
  "log_sources": { "docker_logs_over_ssh": null }
}
```
