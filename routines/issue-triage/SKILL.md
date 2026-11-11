---
name: issue-triage
description: Hourly first-line support triage of Music Assistant issues, HA core issues and tagged support discussions, kept on a board in this thread's side panel
---

# Support issue triage

You are the routine thread for this job. Each scheduled run arrives as a new turn in this thread.
Read `~/git/dotfiles/routines/state/issue-triage.json` first, then do the run below, then write the state
back and commit only that file in `~/git/dotfiles` as `Marvin Schenkel <marvinschenkel@gmail.com>` with the
message `issue-triage: run <YYYY-MM-DD HH:MM>`. Never push.

Before anything else in a run or a reply, run the sync (see "Sync before the run"). It folds in the posts
Marvin made from the board's Post button and refreshes every derived fact, so never re-derive those by hand.

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

## Sync before the run

```
python3 ~/git/dotfiles/routines/issue-triage/sync.py ~/git/dotfiles/routines/state/issue-triage.json \
  --report /tmp/issue-triage-sync.json
```

`sync.py` computes everything that is a fact rather than a judgement, for every card, every run: board
posts from the Post button (folded in like a `reply <n>`), the newest human comment (`gh`, `last`), who is a
teammate, PR state, test asks (`test asked` badge), closed issues (moved to `gone`, their `design` and
`followups` rows pruned), milestones, the release table and `sync.impact` (`affected`: the reporter, body
thumbs, me-too commenters and authors of duplicates and linked issues; `idle_days` since a non-team human
spoke; the reporter's `channel` and `version`). It never sets or clears `ask`. A teammate is a
comment author with authorAssociation MEMBER, OWNER or COLLABORATOR, or a `codeowners` login in a provider
manifest on server `origin/dev`; the issue's own author never counts as a teammate on that issue.

Then work through its report; these are the judgement calls left to you:
- `team_new`: read the comment. If it covers the card's draft, clear `reply`, `action` and `ask`;
  otherwise redraft. A card never stays on Marvin's list for a reply he already gave.
- `reporter_new`: read it and act on it like a fresh update. After a test ask, record the result as
  `["ok", "Tested <MM-DD>", "tested"]`, or `still broken` when it failed.
- `prs_merged_since`: do the merged PR bookkeeping below, set `col` to `merged` and clear `ask` unless
  something besides the release is open. A merged library PR (airplay-cli and the like) gets `ask` `merge`
  until it is released and pinned.
- `prs_opened_since`: someone else's fix moves the card to `dev`; our own PR is linked on the card.
- `new_issues`, `ha_core`, `discussions_tagged`: triage them as below.
- `merged_prs`: bookkeeping for every referenced issue, including issues assigned to teammates; a PR that
  only fixed a test environment is not the issue's fix.

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
  comes back. Then submit a draft PR with the fix and babysit the PR until Bot-MArley approved the head.
  Assign Marvin to the related issue so other people do not pick it up.
- Right after opening the draft PR, comment `@Bot-MArley review` on it. After every push, comment
  `@Bot-MArley recheck`. Its review on the head is the latest one whose `commit_id` equals the PR head SHA.
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

## Possible issue states (the card's `col`)

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

## Lanes on the board

The board's lanes show whose move it is; build.py derives them, nothing stores them. `col` above stays on
every card as the outcome and shows as a small tag.

| lane | holds |
|---|---|
| Needs reply | `ask` is `reply-test`, `reply-info` or `reply-answer`: a draft waits for Marvin |
| Needs decision | `ask` is `input`, `design`, `merge` or `nudge` |
| In progress | no `ask`, and a running session (`fix_thread` without `done`), our own open PR that isn't test-asked yet, or a `local fix` |
| Waiting on teammate or release | no `ask`, and `col` is `merged` or `dev`, or `waiting_on` is `team` |
| Waiting on reporter | everything else: we spoke last, a test or info ask is out |

`ask` is the only "needs Marvin" signal: set it on every card that needs him and clear it when it doesn't.
In the first two lanes cards are grouped by `ask`. When a card needs two things, pick the one that
unblocks it. Set `waiting_on` only to override the default lane, for example `team` while a teammate's PR
or answer is pending.

Whenever you set an `ask`, also set these, which the attention page ranks on:
- `effort`: minutes Marvin needs for the ask, not what the fix costs. A reply he only has to approve is 5 to
  10, an input question 10 to 20, a design call 30 or more.
- `regression`: `{"broke_in": "2.10.9", "worked_in": "2.10.8", "on": "stable" | "beta" | "dev"}` once the
  git log between the two versions confirms it, otherwise `false`. A claim in the issue alone is not enough.
- `domains`: the provider or player domains that carry the bug, as narrow as the evidence allows
  (`["sonos_s1"]`, not `["sonos"]`).

Links. Keep `links` on a card current: `[{"id": "music-assistant/support#6935", "rel": "duplicate_of" |
"blocked_by" | "related", "src": "model"}]`, full `owner/repo#n` ids. `blocked_by` means the card can't move
before that item is done. pr-review writes `fixes` on the PR side, so don't. Never link an advisory id.

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

- When one of our draft PRs is approved by Bot-MArley on its head, the draft reply becomes a question asking
  the user to verify the fix. Use Marvin's "devaddon" saved reply. The gh token cannot read saved replies,
  so copy the text from his most recent test ask comment; the canonical copy is his comment on
  support#6481. Keep the `[!NOTE]` header, keep both the HAOS and the Docker sections unless the issue
  states the install type, replace `pr-NNNN` in both places with the server PR number, leave
  `frontend_repo` blank and end with one short paragraph on what to test for this issue.
- When a PR with a related issue gets merged, update the issue as below and draft no reply. Marvin closes
  every fixed issue himself with a closing message when the release ships, so a "fixed, ships in the next
  release" or "confirm once you're on it" reply is never drafted, and an open test ask on that card is
  dropped. A Fix merged card only needs Marvin when something besides the release is open: the reporter
  says it's still broken, a design call, or a question the fix doesn't answer.
  - Set the "Fix to be confirmed" label.
  - With the "backport to stable" label on the PR, set the milestone to the next patch version, for
    example 2.10.5. This holds even when the cherry-pick conflicts; put a muted `backport?` badge on the
    card then.
  - Without a backport label: if the PR can be backported easily, give the card a `backport?` badge in
    the Fix merged column. If it cannot, set the milestone to the next minor version, for example 2.11.0.
- Milestone numbers live in `milestones` in the state file. Create a missing milestone in the support repo
  and record its number.
- Missing or conflicting cherry-picks never set an `ask`. Marvin does all cherry-picks at
  once before the patch release. Keep a muted `backport?` badge if useful, but no action and no place in
  the attention list for it.

## GitHub writes

The run does the writes this spec asks for on its own: pushing fix branches, opening draft PRs,
posting `@Bot-MArley review` and `recheck` comments, babysitting, assigning Marvin and the merged PR bookkeeping above.

The run posts only one kind of comment on its own: an info ask, under the rules in "Autonomous info asks"
below. Every other reply to a reporter, every discussion comment and every reply on a PR review thread is
drafted on the card and only goes out when Marvin posts it from the board or answers in this thread with
one of the replies below. Every comment starts with:

```
> [!NOTE]
> This comment was written by Claude on Marvin's behalf
```

## Autonomous info asks

Marvin allows the run to post an info ask on his behalf, without asking, when all of these hold. Skip the
whole section when `auto_post.enabled` in the state file is false.

- The card is in `info` with `ask` `reply-info`, in `music-assistant/support`, not a discussion and not
  assigned to someone else. Test asks, answers, design replies, HA core issues and discussions always wait
  for Marvin. A card with a `fix_thread` (fix, repro or discussion session) waits for that session.
- The last comment sweep ran this run, the issue is open, and the reporter (or another user, not Marvin,
  a teammate or a bot) wrote the newest comment. Nothing from Marvin or a teammate since the reporter's
  last comment, and no earlier ask of ours that the reporter hasn't answered yet: never two asks in a row.
- The ask doesn't repeat anything already asked or already answered in the thread, including the triage
  bot's diagnostics request. Re-read the whole thread right before posting.
- The draft follows the content rules: the NOTE header, short, one clear ask with the exact steps (which
  provider's log level, where in Settings, what to do while it logs), a question rather than a claim when it
  hinges on an unconfirmed assumption, no diagnosis stated as fact, no promises about fixes or releases.
- Every UI step is checked against the code, not written from memory: labels and pages from the
  frontend's `src/translations/en.json` on `origin/main` (and the view that uses them), config entries from
  the server on `origin/dev`. Known paths: a provider's log level is an advanced setting (provider
  settings, "Show advanced settings", "Log level"); the full log is "Download logfile" on Settings >
  System > Diagnostics.

GPT Sol check. Put every candidate of this run in one file in a fresh temp dir: the rules above, then per
card the issue number, the full thread text (body and comments, bots marked), the card's `checked` evidence
(GPT can't open attachments, so findings from diagnostics or logs must be in the file or it flags them as
unsupported), the verified UI paths the draft uses, and the draft. Then run, once per run:

```
copilot -p '<instructions>' --model gpt-6.1-sol --reasoning-effort medium --add-dir <dir> \
  --allow-tool read --deny-tool write --deny-tool shell --deny-tool url --deny-tool memory --no-ask-user -s
```

The instructions ask GPT to judge each draft against the thread and the rules above, and to answer with one
JSON line per card: `{"n", "verdict": "post" | "revise" | "marvin", "reason", "text"}`, where `text` is the
improved ask for `revise`. Weigh each verdict yourself:
- Both agree it should go out: post it.
- `revise`: settle on one text with GPT's point taken into account, and run one more check on just those
  cards. If GPT's revised text is one you accept as it is, that is agreement and it goes out. If you still
  disagree after that round, the card goes to Marvin.
- The header is never GPT's: strip whatever header GPT's text carries and put the exact NOTE header
  back (GPT rewrote it to "written by Copilot" in the dry run).
- `marvin`, or any disagreement left: the card stays on Marvin's list with both versions and GPT's
  objection in the card's notes.

Held asks. Whenever a card with an `info` draft (`ask` `reply-info`) does not go out on its own, give it the
badge `["warn", "Auto-post held: <short reason>", "auto held"]` and start its `action` with
`Auto-post held: <reason>.` Reasons: GPT disagreement after the recheck, a `fix_thread` session on the card,
an earlier ask of ours still unanswered, a repeat of something already asked, a discussion, an HA core issue,
assigned to someone else, or `auto_post.enabled` false. A card without a draft, or where Marvin or a
teammate spoke last, gets no badge: there is nothing to post. Drop the badge when the ask goes out, when the
draft is cleared, or when the reason no longer holds.
There is no cap per run. Post with `gh issue comment <n> -R <repo> --body-file -`, then treat it like a
`reply <n>`: clear `reply`, `action` and the attention badges, add the waiting badge, refresh `gh`, and add a
note `<MM-DD HH:MM> run: posted on your behalf (<url>), GPT: <verdict>, <one-line reason>`.

## Merging with earlier runs

Merge each run into the state of the previous runs. An issue that a previous run worked on and that has not
changed since stays on the board until Marvin acted on it. A card only leaves the board when its issue gets
closed, or when Marvin replies `drop`. Closed and dropped issues go to `gone`, which stays in the state file
and is never shown on the board.

## Card field `since`

`since` is the time the card was first seen. Never overwrite it when a card moves lanes; build.py marks a
card "new" when `since` equals the run time.

## Report

Write the state file, then build the board:

```
python3 ~/git/dotfiles/routines/issue-triage/build.py ~/git/dotfiles/routines/state/issue-triage.json \
  --full ~/.claude-teamB/routine-reports/issue-triage.html
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
- Change the layout in `build.py`, never by hand, so the board stays stable from run to run.
- Last, run the attention build, which ranks the asks of every routine on one page:

  ```
  python3 ~/git/dotfiles/routines/attention/build.py --source issue-triage
  ```

The full board:

- Header: the title and only "Last run <time>". No run narrative, no list of dropped issues.
- A filter box and an "Only cards that need attention" toggle.
- One lane per turn (see "Lanes on the board"), with `ask` groups in the first two. Within a group or
  lane, cards are sorted by urgency, then by the most recent activity. Cards without `ask` are faded.
- Clicking a card opens it in a dialog. A card with an `ask` starts with a highlighted pane holding
  a one or two sentence summary of the action needed. Then the badges, a summary of what was done and the
  status, the facts with the optional PR link, the draft reply with a copy button and a Post button, the
  run notes, what the fix changes, how it was checked, the analysis and the diff.
- The Post button only works through `routines/report_server.py`, the LaunchAgent's server. It posts the
  draft with `gh` straight away and logs it. It refuses when the issue is closed, when a comment landed
  after the card's `gh.at` or when the page is older than the draft, and Marvin then asks in the thread.
  So keep `gh.at` current on every card and redraft the reply whenever a newer comment changes it.
- Cards in Needs decision have Discuss, Fix and Repro buttons that copy `discuss <n>`, `fix <n>` or
  `repro <n>` for Marvin to paste here; the board can't start a session itself.
- The release table from `release_table`, the design calls for Marvin and the follow-ups spotted.

Badges are `[tone, label, kind]` with tone one of `bad`, `warn`, `info`, `ok`, `muted`. They are facts on the
card (test asked, tested, still broken, booked, local fix, auto held, backport?); they never decide whether
a card needs Marvin, `ask` does. `backport?` is muted information.

No badges like "draft reply"; Marvin expects those to be there when he opens the issue. Set `action` on
every card with an `ask`; it is the text of the highlighted pane.

End the turn with a chat summary of this run's changes only. Say what changed in a few sentences. If the
run posted info asks on its own, list them next under "Posted on your behalf", one line each with the issue,
what was asked and the comment link. Then paste the attention build's output as it printed it: the `+`
lines, if any, and the `attention:` line. The attention page holds the list of what needs Marvin, so the
summary doesn't list asks. Write every issue number as a link to its card on the board,
filtered and opened: `[#6823](http://127.0.0.1:8765/issue-triage.html?q=6823#c-6823)`; a core card uses
`?q=<n>#c-core-<n>`.

## Replies

Every session launched from this thread or the board (fix, repro, discussion) runs on Marvin's main Claude
account: pass `modelSelection` `{"instanceId":"claudeAgent","model":"claude-opus-5-5"}` to
`t3_thread_launch`. Never let it inherit this routine's `claudeAgent_claude_2` instance.

Marvin acts on cards by replying in this thread. Handle the reply right away, outside the scheduled run.
The attention thread forwards the commands Marvin gives there to this thread as plain messages in the same
grammar; handle them like his own replies.
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
  `workspaceStrategy` `{"type":"root"}`, `modelSelection` `{"instanceId":"claudeAgent","model":"claude-opus-5-5"}`, title `Fix: <short issue title>`, and a message that tells the
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
- `repro <n>` and `discuss <n>` (each with optional extra instructions): start a repro or a discussion
  session the same way as `fix`, with title `Repro: <short title>` or `Discuss: <short title>` and the same
  card context. A repro session tries to reproduce first and asks Marvin before it fixes anything; a
  discussion session changes no code and posts nothing. Store it in `fix_thread` with `kind`; set `done`
  when the session reports back.
- `release <milestone>`: show the release table for that milestone with the on-stable check, plus a short
  closing comment per issue (the NOTE header, which release it shipped in, ask to reopen if it isn't
  fixed). Post nothing yet. `release <milestone> post` then posts every closing comment, closes the issues
  and moves them to `gone`.
- `done <n>` or `done <n> <note>`: Marvin handled it himself. Clear `action`, the draft reply and the
  attention badges, and add a dated note. The card stays until the issue closes.
- `drop <n>` or `drop <n> <reason>`: take the card off the board and append it to `gone` with the date and
  the reason.
- Anything else: answer from the state file, and check GitHub when the state may be stale.

After a reply that changes the state, write and commit the state file with the message
`issue-triage: <verb> <n>`. After `edit` and after every forwarded command, rebuild the board and refresh
the side panel, so the Post button carries the new draft; otherwise the next run shows the change. Then run
the attention build as the last step of every handled reply and answer with one confirmation line, the link
to what was posted and the build's output.

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
      "ask": "reply-test | reply-info | reply-answer | input | design | merge | nudge",
      "effort": 10,
      "regression": false,
      "domains": ["airplay"],
      "links": [{ "id": "music-assistant/support#6935", "rel": "duplicate_of", "src": "model" }],
      "badges": [["info", "Test asked 10-21", "test asked"]],
      "reply": "draft reply, starting with the NOTE header",
      "prs": [{ "url": "https://github.com/music-assistant/server/pull/7131", "label": "server#7131 (ours, draft, CI green)" }],
      "branch": "fix/<slug> @ <sha>, worktree server-worktrees/<dir>",
      "fix": "",
      "checked": "",
      "plan": "",
      "diff": "",
      "bookkeeping": [{ "id": "6836-milestone", "text": "", "labels": ["Fix to be Confirmed"], "milestone": "2.10.8" }],
      "review_replies": [{ "repo": "music-assistant/server", "pr": 7131, "comment_id": 0, "thread_id": "PRRT_...", "body": "" }],
      "fix_thread": { "id": "<threadId>", "title": "Fix: ...", "kind": "fix", "done": false },
      "waiting_on": "team",
      "milestone": "2.10.8",
      "sync": { "written by sync.py each run, read only": true },
      "notes": ["10-21 07:38 run: ..."]
    }
  ],
  "design": [["#6808 short title", "the decision and its options", "recommendation"]],
  "followups": ["one line per follow-up"],
  "release": { "title": "2.10.7 released 10-17, 2.10.8 queued", "rows": [["issue", "fix", "on stable", "note"]] },
  "milestones": { "2.10.8": 39 },
  "auto_post": { "enabled": true },
  "release_table": { "2.10.8": [{ "n": 6833, "title": "", "prs": ["server#7131"], "on_stable": true }] },
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
