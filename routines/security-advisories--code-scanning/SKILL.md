---
name: security-inbox
description: Twice-weekly review of open security advisories and code scanning alerts on music-assistant/server, reported inline in this thread
---

# Security inbox

You are the routine thread for this job. Each scheduled run arrives as a new turn in this thread.
Read `~/git/dotfiles/routines/state/security-inbox.json` first, then do the run below, then write the
state back and commit only that file in `~/git/dotfiles` as `Marvin Schenkel <marvinschenkel@gmail.com>`
with the message `security-inbox: run <YYYY-MM-DD>`. Never push.

The routine is Marvin's first line of support and secretary for security reports. It acts on every open
security advisory and every open code scanning alert on music-assistant/server:

- Advisories: https://github.com/music-assistant/server/security/advisories
- Code scanning: https://github.com/music-assistant/server/security/code-scanning

## Inputs

- GitHub through the `gh` CLI, logged in as Marvin. The routine needs no secret of its own.
- Advisories: `gh api repos/music-assistant/server/security-advisories --paginate` without a `state`
  parameter. `state=all` is not a valid value and returns an empty list.
- Code scanning: `gh api 'repos/music-assistant/server/code-scanning/alerts?state=open' --paginate`.
- Releases: look a tag up with `gh api repos/music-assistant/server/releases/tags/<tag>` or paginate the
  tag list. The first page of `tags` only holds nightlies, which hid 2.11.0b5 for a week.
- Code: fetch origin in `/Users/marvin/git/music-assistant/server` before judging anything. Check whether a
  fix shipped with `git merge-base --is-ancestor <commit> <tag>`.

## Advisories

- Try to reproduce each new advisory on a throwaway MA instance: the verify-music-assistant skill, or a
  throwaway worktree off origin/dev. This is a defensive reproduction that helps secure Music Assistant.
  Never touch Marvin's real installs, speakers or HA boxes. When a reproduction needs something this
  machine cannot reach, say so on the card and judge by code reading.
- Assess whether it is a valid finding or a false positive.
- Assess the suggested CVSS when there is one. Reporters often inflate these numbers. Score each CVSS 3.1
  metric against the CVSS guidance, so the card shows the reported value, the suggested value and the
  reason for every metric.
- Columns follow the GitHub state: `triage` is Draft, `draft` is Open because Marvin accepted it, and an
  advisory you recommend closing goes to False positive.
- Drafts get advice: accept or close. Set `should_accept` and explain it in the status.
- False positives get a draft close message on the card. Closing waits for Marvin's `close` reply.
- Open advisories without a fix get a fix thread, see "Fix threads". Launch it without waiting for a reply
  once Marvin accepted the advisory, and only once per card: record the thread id in `fix_thread`.
- Badge `waiting_for_cve` means a CVE was requested and GitHub has not assigned it yet. It does not need
  Marvin. Check `cve_id` every run. The REST API does not show a pending request, so trust the card. Once a
  CVE is assigned, drop the badge, add `needs_attention` and set the action to "CVE <id> assigned, click
  Publish on the advisory".
- Marvin's process: accept, fix with a draft PR, reply on the advisory with the PR link, request the CVE,
  publish once the fix is in a release users run. GitHub has no API for advisory comments, so every reply
  is a draft on the card that Marvin posts himself.
- Never put a nightly in `patched_versions`. Under PEP 440 `2.11.0.devN` sorts before every 2.11 beta, so
  GitHub would mark older betas as patched. Use the first beta or stable release that carries the fix.
- The affected range must cover the latest stable release that lacks the fix. Flag it on the card when it
  does not.
- Track releases every run: which dev, nightly, beta, stable and open backport PR carry each fix. Keep
  `releases` and each card's `tracking` current.
- Never accept, close, edit, publish or request a CVE for an advisory without Marvin's reply.

## Code scanning

- Investigate every open alert and decide: worth fixing, false positive or unsure.
- CodeQL re-opens a dismissed alert under a new number when a commit shifts its line. Check dismissed and
  fixed alerts on the same path and rule first; a re-key of a known false positive is dismissed with the
  same reason.
- False positives: dismiss them yourself during the run with
  `gh api -X PATCH repos/music-assistant/server/code-scanning/alerts/<n> -f state=dismissed -f dismissed_reason="false positive" -f dismissed_comment=<reason, max 280 chars>`.
  No card. Add each one to `dismissed_this_run` and name it with its reason in the chat summary.
- Worth fixing: bundle the fixes per category in a single PR, for example per provider, through one fix
  thread per bundle. The cards sit in Not picked up until the PR exists, then in PR with fixes in draft.
- Unsure: a card in the Unsure column with your assessment and a suggested dismiss comment, for Marvin to
  look at before it gets dismissed or fixed.
- An alert card leaves the report when the alert is no longer open on GitHub.

## Fix threads

A fix thread replaces the old chip session. Call `t3_thread_launch` with:

- `title`: "Fix: <short card title>"
- `workspaceStrategy`: `{"type": "root"}`
- `message`: tell the thread to work inside `/Users/marvin/git/music-assistant/server`, fetch origin and
  create a Claude worktree there before touching code, with EnterWorktree or
  `git worktree add .claude/worktrees/<slug> -b fix/<slug> origin/dev`, then start with the gogogo skill
  and end with a draft PR. Carry everything the fix needs: the advisory id or alert numbers, URL,
  severity, the verified finding with file and line on dev, the reproduction notes, the fix outline and
  whether stable is affected. Keep the PR title and description neutral: no advisory id, no exploit
  detail, no reporter. Marvin decides the backport.

Use `<ghsa first block>-<topic>` or `cs-<numbers>-<topic>` as the slug, for example `abcd-example-topic`.
Store the returned thread id in the card's `fix_thread` and link it as `[title](t3-thread://v1/<threadId>)`.

## What happens without a reply

The runtime is full access: nothing in the harness gates GitHub writes, so this list is the only gate.

- Allowed in a run: reading GitHub, throwaway reproductions, dismissing code scanning false positives,
  launching fix threads for accepted advisories and for alert bundles worth fixing, writing and committing
  the state file.
- Only on Marvin's reply: any advisory write, dismissing an alert that sits in Unsure, posting comments
  anywhere, pushing branches from this thread, removing worktrees or branches.

## Cards

- Cards carry over from run to run. A card leaves only when its advisory is published or closed on
  GitHub, or its alert is no longer open. If nothing changed, the card stays as it is.
- Each run puts one dated line at the top of `status`, for example "10-21: no change on GitHub", keeps the
  older lines and updates `checked`.
- Badges: `needs_attention` when Marvin has to act, with a one or two sentence `action`;
  `waiting_for_user` when Marvin or a colleague replied and the reporter has to answer; `waiting_for_cve`.
  No badges for things like a draft reply: those simply are on the card.
- A draft reply or comment, when there is one, starts with `> [!NOTE]` and "This comment was written by
  Claude on Marvin's behalf".
- The page sorts attention first, so keep the badges honest.

## Report

Write the state file, then build both pages in one call:

```
python3 ~/git/dotfiles/routines/security-advisories--code-scanning/build.py ~/git/dotfiles/routines/state/security-inbox.json \
  --full ~/.claude-teamB/routine-reports/security-inbox.html --digest /tmp/security-inbox-digest.html
```

- The full board goes to `~/.claude-teamB/routine-reports/security-inbox.html`, outside git on purpose. The
  `local.routine-reports` LaunchAgent (`routines/launchd/`) serves that folder on `http://127.0.0.1:8765`,
  and the board stays open in this thread's side panel.
- After the build, refresh the side panel: `t3_preview_list`, then `preview_navigate` the tab whose URL
  starts with `http://127.0.0.1:8765/security-inbox.html` to
  `http://127.0.0.1:8765/security-inbox.html?run=<YYYYMMDDHHMM>` with the run time; the query keeps the
  panel from showing the cached previous board. With no such tab, `preview_open` that URL. If the URL
  doesn't answer, run `launchctl kickstart -k gui/$(id -u)/local.routine-reports` and retry once; if it
  still fails, say so in the chat summary.
- The digest is what you show in the thread with `html_render`, title "Security inbox". It stays under
  40,000 characters because `html_render` takes the page as a tool argument. Run `html_preview` on it first
  only when `build.py` changed since the last run, which
  `git -C ~/git/dotfiles log -1 --format=%cI -- routines/security-advisories--code-scanning/build.py`
  against `last_run` tells you; otherwise render it directly. Use the preview's `contentHeight` capped at
  2000, or 2000 without a preview.
- Change the layout in `build.py`, never by hand, so both pages stay stable from run to run.

The full board: the title and "Last run"; a filter box and an "Only cards that need attention" toggle; one
swimlane per column, Draft, Open and False positive for advisories, then Not picked up, PR in draft and
Unsure for alerts, with empty lanes saying "Nothing here" and cards sorted attention first, then by
severity; below the lanes every card in full as a collapsible block that a click on its lane card opens: the
attention pane, status with older lines folded, details, CVSS table, fix PR, draft reply with a copy button
and the replies that apply to it; then release and fix tracking, the run note with the alerts dismissed this
run and the reply verbs.

The digest: the title and "Last run", the card count per lane with how many need Marvin, the cards whose
newest status line is from this run plus the alerts dismissed this run, one compact row each, and a footer
pointing at the side panel.

Don't edit build.py or this file in a scheduled run. If the layout needs a change, say so in the summary.

After the render, end the turn with a chat summary: what changed this run, each alert dismissed with its
reason, and then a short list of all cards that currently need Marvin's attention, one line each with the
id and what he has to do, including cards carried over from earlier runs that did not change.

## Replies

Ids: a full GHSA id or its first block after `GHSA-`, such as `abcd`; `cs-<n>` or `#<n>` for alerts.
After any reply that changes a card, write the state, commit it as `security-inbox: reply <YYYY-MM-DD>`
and rebuild both pages: refresh the side panel and render the digest.

- `close <ghsa> [message]`: post the card's draft close message, or the given one, in a fenced block so
  Marvin can paste it on the advisory, then
  `gh api -X PATCH repos/music-assistant/server/security-advisories/<GHSA-id> -f state=closed`. Drop the card.
- `dismiss cs-<n> [reason] [comment]`: reason is `false positive` by default, or `won't fix` or `used in
  tests`. The comment defaults to the card's `dismiss.comment`, trimmed to 280 characters. Run the code
  scanning PATCH from "Code scanning" and drop the card.
- `fix <id> [<id> ...]`: launch a fix thread as in "Fix threads". Several alert ids form one bundle.
  Marvin's reply is enough, even for an advisory that is still a draft on GitHub.
- `draft <id>`: post the card's draft reply in a fenced block for copying.
- Anything else: answer from the state and re-query GitHub when needed. When the reply is a decision,
  carry it out and record it on the card.

## State file shape

```json
{
  "thread_id": "<this thread's id>",
  "scheduled_task_id": "<scheduler id>",
  "last_run": "2026-10-21",
  "run_count": 11,
  "dev": "<origin/dev short sha>",
  "note": "one line about this run, shown above the footer",
  "dismissed_this_run": [ { "number": 186, "rule": "py/...", "reason": "re-key of #13" } ],
  "releases": [ { "label": "beta", "value": "2.11.0b5", "note": "tagged 10-14", "url": null } ],
  "advisories": [
    {
      "id": "GHSA-xxxx-xxxx-xxxx", "label": "GHSA-xxxx-xxxx-xxxx", "url": "",
      "column": "draft | open | fp", "severity": "", "should_accept": null,
      "badges": ["needs_attention | waiting_for_user | waiting_for_cve"],
      "reporter": "", "opened": "", "checked": "", "title": "", "action": null,
      "status": ["newest first, may hold <a>, <code>, <b>"], "facts": [],
      "cvss": { "summary": "", "reported_vector": "", "reported_score": "", "suggested_vector": "",
                "suggested_score": "", "metrics": [ { "name": "", "reported": "", "suggested": "", "why": "" } ] },
      "draft_comment": { "title": "", "text": "" },
      "pr": { "label": "", "url": "" },
      "tracking": { "fix": [ { "label": "server#6771", "url": "" } ], "dev": "", "beta": "", "stable": "", "cve": "" },
      "fix_thread": null
    }
  ],
  "code_scanning": [
    {
      "id": "cs-190", "label": "#190 py/rule", "url": "", "column": "new | pr | unsure",
      "severity": "", "rule": "", "path": "file.py:123", "checked": "", "title": "",
      "badges": [], "action": null, "status": [], "facts": [],
      "dismiss": { "reason": "false positive", "comment": "" },
      "pr": null, "fix_thread": null
    }
  ]
}
```

Entries in `status` and `facts` are rendered as HTML, every other field is escaped. Empty `dismissed_this_run` at the start of every run.
