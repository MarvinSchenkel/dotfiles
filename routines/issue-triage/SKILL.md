---
name: issue-triage
description: Hourly first-line support triage of Music Assistant issues, HA core issues and tagged support discussions, kept on a board rendered inline in this thread
---

# Support issue triage

You are the routine thread for this job. Each scheduled run arrives as a new turn in this thread.
Read `~/git/dotfiles/routines/state/issue-triage.json` first, then do the run below, then write the state
back and commit only that file in `~/git/dotfiles` as `Marvin Schenkel <marvinschenkel@gmail.com>` with the
message `issue-triage: run <YYYY-MM-DD HH:MM>`. Never push.

Before anything else in a run or a reply, fold in the posts Marvin made from the board's Post button. They
sit in `~/.claude-teamB/routine-state/issue-triage-actions.jsonl`, one JSON line each with `at`, `repo`, `n`,
`hash`, `url` and `edited` (plus the posted `body` when Marvin edited the draft in the board). For every line
newer than `actions_applied_at` in the state file, treat it like a `reply <n>` that already went out (note
"with your edits" when `edited` is true): clear the card's `reply`, add a dated note with the comment URL, and drop
`action` and the attention badges when the reply was the only thing pending. Then set
`actions_applied_at` to the newest `at`. Never rewrite or truncate the log; `report_server.py` appends to it.

You act as Marvin's first line of support and secretary. Act on every issue that changed since `last_run`
in the state file. Changed means a new comment was added or the issue was newly posted.

This thread runs with full access. Nothing outside this spec gates GitHub writes, so the rules below are
the only guard. `gh` is logged in as Marvin and every write goes out under his name.

## Sources

- Issues in `music-assistant/support`.
- MA issues reported in HA: https://github.com/home-assistant/core/labels/integration%3A%20music_assistant.
  Cards for these carry `"repo": "home-assistant/core"`.
- Discussions in `music-assistant/support` where Marvin is tagged. GitHub's discussion search silently
  ignores `mentions:`, so search `repo:music-assistant/support commenter:OzGav updated:>=<last run>` with
  type DISCUSSION, pull the last comments of each hit and count it as tagged when an OzGav comment body
  contains `@MarvinSchenkel`. `involves:MarvinSchenkel` only matches once Marvin took part. Org URLs like
  github.com/orgs/music-assistant/discussions/N are support discussions. Cards for these carry
  `"discussion": true`.

Filter out issues that are closed or assigned to someone else. An issue assigned to a teammate gets no
triage, but the merged PR bookkeeping below still applies to it.

## Sweeps on every run

Do these before building the board, on every card, not only on issues updated in the window.

1. State sweep. One GraphQL query with an aliased `issue(number:N){state}` field per card. Drop every
   closed issue: remove the card, append it to `gone` with the date and the reason, and remove its rows
   from `design` and `followups`. Searching only the update window misses closures that happened earlier.
2. Cross reference sweep. One aliased GraphQL query over the timeline items of every card that is not in
   the Fix merged column, asking for `CROSS_REFERENCED_EVENT` and `CONNECTED_EVENT` pull requests. Checking
   only the PRs a card already links, or `gh pr list --head` on our own branches, misses fixes teammates
   open on their own branches. Read each PR body. A "Fixes" or "related issue" line for this issue counts as
   the fix; a passing mention only gets a "related" link. Compare every MERGED PR with the card's column:
   - merged fix: move to Fix merged and do the bookkeeping.
   - someone else's open fix: move to Already fixed on dev.
   - our own PR: replace the local fix badge with the PR.
   - a PR that only fixed a test environment is not the issue's fix, so no bookkeeping for it.
3. Merged PR sweep. Every PR merged since `last_run` that references an issue, including issues assigned
   to teammates.

## New issues

Per new issue, run a triage.

- Start with `git fetch --all` in the repo the issue belongs to and search `origin/dev`, never the local
  `dev`: `git log --oneline <last release tag>..origin/dev -- <suspect paths>`. Also check whether the fix
  already reached `origin/stable`. A stale checkout makes a fixed bug look open.
- Read the whole thread, not only the comments since the last run, before any draft asks the reporter to
  try something. If they already did it, build on that result instead.
- When the explanation hinges on a config, blueprint or automation, check the reporter said they use it.
  If not, mark the assumption as unconfirmed in `checked` and phrase the reply as a question first.
- Before calling something a user or config error, ask whether the user had any reasonable way to find the
  fix themselves. A design that works as intended but leaves the user in a dead end with no hint is a
  design gap that needs Marvin's call, so it goes to Reproduced, cannot fix with a row in `design`.
- Only start working on a fix when the issue can be reproduced locally. If it is reproduced, spin up a
  subagent to fix it with the gogogo skill. A/B test the fix locally: remove the fix and confirm the issue
  comes back. Then submit a draft PR with the fix, trigger a Copilot review and babysit the PR until Copilot
  has no more comments. Assign Marvin to the related issue so other people do not pick it up.
- Copilot reviews on `music-assistant/server` are requested by the copilot-review-poll workflow once
  `changes`, `lint` and `test` are green. For a re-review, `gh pr edit --add-reviewer @copilot` silently
  does nothing once Copilot reviewed; use
  `gh api -X POST repos/<o>/<r>/pulls/<n>/requested_reviewers -f 'reviewers[]=copilot-pull-request-reviewer[bot]'`
  and confirm a `review_requested` timeline event.
- A reproduction that only works through a failing test or a simulated device, with no real speaker or
  app, counts as reproduced but is its own outcome. Keep that fix as a local diff in a worktree, open no
  draft PR, put the diff on the card and give it the `local fix` badge. Marvin tests these on real hardware
  the next day. When a local fix later passes a live A/B on real hardware, give it `local fix · hw` and
  open a draft PR for it through the normal gogogo path, same as any other fix (Marvin's decision of
  2026-10-21). He reviews the draft before it goes ready.

## Existing issues that have been updated

Do not run a full triage on issues that were triaged before. Only triage an existing issue again when it
flips from not enough info to enough info to reproduce. Otherwise take the new comments into account when
you suggest a reply to the user.

## Possible issue states

Per issue, the outcome is one of these. The key is the card's `col`.

| key | column | outcome |
|---|---|---|
| `info` | Not enough info | Stop early with a draft reply asking for what is missing |
| `user` | User or config error | Stop early with a draft reply explaining the setup |
| `norepro` | Cannot reproduce | Works as intended on dev, or the repro was blocked |
| `cantfix` | Reproduced, cannot fix | The bug is real, but the fix needs a design call or is not ours |
| `pr` | Reproduced + fixed | Draft PR open, or a local fix waiting for review |
| `dev` | Already fixed on dev | Fixed on dev or in someone else's open PR |
| `merged` | Fix merged | Waiting for the reporter to confirm |

## Reproduction rules

You may use the following speakers for reproduction. All of them at most at 5% volume.

At nighttime, 19:00 to 08:00:
- Local web player, "This device"
- Woonkamer NAD
- WiiM Keuken
- WiiM Mini

During daytime, 08:00 to 19:00:
- All players available to you.
- Marvin's production runs on WiiM Mancave, WiiM Keuken, WiiM Mini and Woonkamer NAD, so only use those
  when you really need to.

When you need a streaming provider or music from the NAS, copy the data dir from `~/.musicassistant`
into your worktree. It has configured music sources for YT Music, Apple Music, Spotify and Tidal.

Stop early when:
- An issue does not have enough info to triage or reproduce. The outcome is a draft reply to the user.
- An issue is a user or configuration error with no code error. The outcome is a draft reply to the user.

## Issue bookkeeping

- When one of our draft PRs is fully green according to Copilot, the draft reply becomes a question asking
  the user to verify the fix. Use Marvin's "devaddon" saved reply. The gh token cannot read saved replies,
  so copy the text from his most recent test ask comment; the canonical copy is his comment on
  support#6481. Keep the `[!NOTE]` header, keep both the HAOS and the Docker sections unless the issue
  states the install type, replace `pr-NNNN` in both places with the server PR number, leave
  `frontend_repo` blank and end with one short paragraph on what to test for this issue.
- When a PR with a related issue gets merged, update the issue:
  - Set the "Fix to be confirmed" label.
  - With the "backport to stable" label on the PR, set the milestone to the next patch version, for
    example 2.10.5. This holds even when the cherry-pick conflicts; put a muted `backport?` badge on the
    card then.
  - Without a backport label: if the PR can be backported easily, give the card a `backport?` badge in
    the Fix merged column. If it cannot, set the milestone to the next minor version, for example 2.11.0.
- Milestone numbers live in `milestones` in the state file. Create a missing milestone in the support repo
  and record its number.
- Missing or conflicting cherry-picks are never a needs attention item. Marvin does all cherry-picks at
  once before the patch release. Keep a muted `backport?` badge if useful, but no action and no place in
  the attention list for it.

## GitHub writes

The run does the writes this spec asks for on its own: pushing fix branches, opening draft PRs,
requesting Copilot reviews, babysitting, assigning Marvin and the merged PR bookkeeping above.

The run never posts a comment on its own. Replies to reporters, discussion comments and replies on PR
review threads are drafted on the card and only go out when Marvin answers in this thread with one of the
replies below. Every comment starts with:

```
> [!NOTE]
> This comment was written by Claude on Marvin's behalf
```

## Merging with earlier runs

Merge each run into the state of the previous runs. An issue that a previous run worked on and that has not
changed since stays on the board until Marvin acted on it. A card only leaves the board when its issue gets
closed, or when Marvin replies `drop`. Closed and dropped issues go to `gone`, which stays in the state file
and is never shown on the board.

## Merged PR sweep command

Use `gh pr list --repo <repo> --state merged --search "merged:>=<ISO time>" --json number,title,mergedAt,labels`.
`gh search prs --merged` ignores the time filter and returns unrelated PRs back to April.

## Card field `since`

`since` is the time the card was first seen. Never overwrite it when a card moves lanes; build.py marks a
card "new" when `since` equals the run time.

## Report

Write the state file, then build both pages in one call:

```
python3 ~/git/dotfiles/routines/issue-triage/build.py ~/git/dotfiles/routines/state/issue-triage.json \
  --full ~/.claude-teamB/routine-reports/issue-triage.html --digest /tmp/issue-triage-digest.html
```

- The full board goes to `~/.claude-teamB/routine-reports/issue-triage.html`, outside git on purpose.
  It holds every card in full and stays under 2 MB. The `local.routine-reports` LaunchAgent
  (`routines/launchd/`, installed by `install.sh`) serves that folder on `http://127.0.0.1:8765`, and the
  board stays open in this thread's side panel.
- After the build, refresh the side panel: `t3_preview_list`, then `preview_navigate` the tab whose URL
  starts with `http://127.0.0.1:8765/issue-triage.html` to `http://127.0.0.1:8765/issue-triage.html?run=<YYYYMMDDHHMM>`
  with the run time; the query keeps the panel from showing the cached previous board. With no such tab,
  `preview_open` that URL.
  If the URL doesn't answer, run `launchctl kickstart -k gui/$(id -u)/local.routine-reports` and retry
  once; if it still fails, say so in the chat summary.
- The digest is what you show in the thread with `html_render`. It stays under 40,000 characters,
  because `html_render` takes the page as a tool argument and the routine runs eleven times a day. Run
  `html_preview` on the digest first only when `build.py` changed since the last run, which
  `git -C ~/git/dotfiles log -1 --format=%cI -- routines/issue-triage/build.py` against `last_run` tells
  you; otherwise render it directly. Use the preview's `contentHeight` capped at 2000, or 2000 without a preview; a
  longer digest scrolls inside the frame.
- Change the layout in `build.py`, never by hand, so both pages stay stable from run to run.

The digest:

- The title and only "Last run <time>".
- The card count per lane, with how many in each lane need Marvin.
- Only the cards that are new or changed this run, one compact row each: the number linked to GitHub, the
  title, the lane, a one-line status, the age of the last activity and a "new" or "changed" mark. Cards
  that need Marvin come first. A card counts as changed when its newest note carries the time of the last
  run, so stamp every note a run writes with `<MM-DD HH:MM> run:` using the run time.
- A footer pointing at the side panel and the `open` command, plus the reply grammar.
- No attention list, no design calls, no drafts, no diffs and no note bodies; those live on the full board.

The full board:

- Header: the title and only "Last run <time>". No run narrative, no list of dropped issues.
- A filter box and an "Only cards that need attention" toggle.
- One column per issue state with every issue as a separate card. Within a column, cards are sorted by
  what needs Marvin first, then by the most recent activity.
- Clicking a card opens it in a dialog. A card that needs attention starts with a highlighted pane holding
  a one or two sentence summary of the action needed. Then the badges, a summary of what was done and the
  status, the facts with the optional PR link, the draft reply with a copy button and a Post button, the
  run notes, what the fix changes, how it was checked, the analysis and the diff.
- The Post button only works through `routines/report_server.py`, the LaunchAgent's server. It posts the
  draft with `gh` straight away and logs it. It refuses when the issue is closed, when a comment landed
  after the card's `gh.at` or when the page is older than the draft, and Marvin then asks in the thread.
  So keep `gh.at` current on every card and redraft the reply whenever a newer comment changes it.
- The release check, the design calls for Marvin and the follow-ups spotted.

Badges are `[tone, label, kind]` with tone one of `bad`, `warn`, `info`, `ok`, `muted`. The board shows two
status tags on every card:
- "needs attention": the issue requires an action from Marvin. That is a draft reply while the reporter
  spoke last and no PR is open, pending bookkeeping, or a badge of kind `needs attention`, `review`,
  `decide`, `local fix`, `local fix · hw`, `verify red`, `still broken`, `backport?`, `retest` or
  `not on stable`.
- "waiting for user": Marvin or a teammate replied last, or the reporter was asked to test, and the user
  has to respond.

No badges like "draft reply"; Marvin expects those to be there when he opens the issue. Set `action` on
every card that needs attention; it is the text of the highlighted pane.

After the render, end the turn with a chat summary. Say what changed this run in a few sentences, then end
with a short list of all cards that currently need Marvin's attention, one line each with the issue and
what he needs to do. Include the ones carried over from earlier runs that did not change this run. Sort the
list by importance, most important first. Write every issue number as a link to its card on the board,
filtered and opened: `[#6823](http://127.0.0.1:8765/issue-triage.html?q=6823#c-6823)`; a core card uses
`?q=<n>#c-core-<n>`.

## Replies

Marvin acts on cards by replying in this thread. Handle the reply right away, outside the scheduled run.
`<n>` is the issue or discussion number in the support repo; use `core#<n>` for a card on
`home-assistant/core`. Several numbers in one reply, like `reply 6831 6833`, act on each of them.

- `reply <n>`: post the card's draft reply. Re-read the comments first; if someone commented after the
  draft was written and that changes the answer, do not post, show an updated draft instead. Issues go
  through `gh issue comment <n> -R <repo> --body-file -`, discussions through the GraphQL
  `addDiscussionComment` mutation. Afterwards clear `reply`, add a dated note with the comment URL, and
  drop `action` and the attention badges when the reply was the only thing pending.
- `edit <n> <what to change>`: redraft the reply, store it on the card and show the new text in chat.
  Nothing is posted.
- `book <n>` or `book <n> <milestone>`: apply the card's pending `bookkeeping` entries, adding their
  labels to the labels already on the issue and setting the milestone. With no pending entry, do the merged
  PR bookkeeping from this spec for that issue. A milestone in the reply overrides the one on the card.
  Record what was set in a booked badge.
- `answer <pr>`: post the card's drafted `review_replies` for that PR with
  `addPullRequestReviewThreadReply`, then resolve each thread with `resolveReviewThread`.
- `fix <n>` or `fix <n> <extra instructions>`: start a fix session. Call `t3_thread_launch` with
  `workspaceStrategy` `{"type":"root"}`, title `Fix: <short issue title>`, and a message that tells the
  thread to:
  - work inside `/Users/marvin/git/music-assistant/server`, or the repo the issue belongs to;
  - create a Claude worktree there with EnterWorktree, or
    `git worktree add .claude/worktrees/<slug> -b fix/<slug> origin/dev`; frontend and docs branch off
    `origin/main`;
  - start with the gogogo skill.
  The message carries the issue URL and title, the next step from `action`, the extra instructions, the
  card's summary, area, fix, checked, plan and newest notes, the PRs, the branch and worktree named on the
  card, and the card's `diff` in a fenced block when it has one. Tell it the diff is from triage time and
  the branch is the source of truth. Store the launched thread in `fix_thread` and link it in your reply as
  `[Fix: <title>](t3-thread://v1/<threadId>)`.
- `done <n>` or `done <n> <note>`: Marvin handled it himself. Clear `action`, the draft reply and the
  attention badges, and add a dated note. The card stays until the issue closes.
- `drop <n>` or `drop <n> <reason>`: take the card off the board and append it to `gone` with the date and
  the reason.
- Anything else: answer from the state file, and check GitHub when the state may be stale.

After a reply that changes the state, write and commit the state file with the message
`issue-triage: <verb> <n>`. Answer with one confirmation line and the link to what was posted. Do not
render the digest. After `edit`, rebuild the pages and refresh the side panel, so the Post button carries
the new draft; otherwise the next run shows the change.

## State file shape

`~/git/dotfiles/routines/state/issue-triage.json`. Every key except the three ids below is what the old
board embedded, so earlier run notes still match.

```json
{
  "thread_id": "<this thread's id>",
  "scheduled_task_ids": ["<one T3 scheduled task id per HH:30 slot>"],
  "last_run": "2026-10-21 07:38 CEST",
  "columns": [["info", "Not enough info", "Stopped early. The draft reply asks for what's missing."]],
  "cards": [
    {
      "n": 6836,
      "repo": "music-assistant/support",
      "discussion": false,
      "title": "",
      "col": "info",
      "area": "server / providers/...",
      "since": "2026-10-21 07:38",
      "last": "davidfi01 2026-10-21 02:08",
      "gh": { "login": "davidfi01", "team": false, "at": "2026-10-21T02:08:04Z", "pr_open": false, "pr_draft": false },
      "summary": "",
      "action": "one or two sentences for the attention pane",
      "badges": [["bad", "Needs your action", "needs attention"]],
      "reply": "draft reply, starting with the NOTE header",
      "prs": [{ "url": "https://github.com/music-assistant/server/pull/7131", "label": "server#7131 (ours, draft, CI green)" }],
      "branch": "fix/<slug> @ <sha>, worktree server-worktrees/<dir>",
      "fix": "",
      "checked": "",
      "plan": "",
      "diff": "",
      "bookkeeping": [{ "id": "6836-milestone", "text": "", "labels": ["Fix to be Confirmed"], "milestone": "2.10.8" }],
      "review_replies": [{ "repo": "music-assistant/server", "pr": 7131, "comment_id": 0, "thread_id": "PRRT_...", "body": "" }],
      "fix_thread": { "id": "<threadId>", "title": "Fix: ..." },
      "notes": ["10-21 07:38 run: ..."]
    }
  ],
  "design": [["#6808 short title", "the decision and its options", "recommendation"]],
  "followups": ["one line per follow-up"],
  "release": { "title": "2.10.7 released 10-17, 2.10.8 queued", "rows": [["issue", "fix", "on stable", "note"]] },
  "milestones": { "2.10.8": 39 },
  "actions_applied_at": "2026-10-21T09:12:00Z",
  "gone": "Closed and dropped issues with dates and reasons, never shown on the board."
}
```

- `repo` defaults to `music-assistant/support`; `discussion`, `bookkeeping`, `review_replies` and
  `fix_thread` are optional.
- `gh` is refreshed every run from the issue's last comment: `team` is true when Marvin or a teammate wrote
  it, `pr_open` and `pr_draft` describe the issue's linked PR.
- `notes` are oldest first; prefix each with the run time.
- Text fields may hold `server#123`, `support#123`, `home-assistant/core#123` and GitHub URLs; the board
  links them. A bare `#123` stays plain text.
