---
name: pr-review
description: Hourly review of changed and open Music Assistant PRs from Bot-MArley's reviews, auto-approval of safe PRs, and a PR backlog report on a local page
---

# PR review

You are the routine thread for this job. Each scheduled run arrives as a new turn in this thread, and
Marvin's replies between runs land here too. Read `~/git/dotfiles/routines/state/pr-review.json` first,
then do the run below, then write the state back and commit only that file in `~/git/dotfiles` as
Marvin Schenkel <marvinschenkel@gmail.com> with the message `pr-review: run <YYYY-MM-DD HH:MM>`. Never push.

This thread runs with full access. Nothing outside this spec gates GitHub writes, so the rules here are
the only gate: post, push, approve or merge only where a rule below or a reply from Marvin says so.

The idea behind the exercise is that Marvin can quickly stay on top of the PRs.

## Inputs

- GitHub through `gh`, already logged in as MarvinSchenkel. No other credentials are needed.
- Baseline: `last_run` in the state file. Every PR entry also records `head_sha`, so compare heads and the
  latest Bot-MArley review time against the state as well as `updatedAt`.
- Local checkouts live in `/Users/marvin/git/music-assistant/<repo>`. Use `origin/dev`, never the local
  `dev` ref.

## Which PRs

Go through every PR that has changed since the last run. Changed means a new commit was pushed, someone
commented or reviewed, or anything else on the PR was modified. Don't focus on newly created PRs only.
Besides changed PRs, review and add every open non-draft PR that isn't in the state file yet, however old
its last update.

Repositories to monitor:

- https://github.com/music-assistant/server
- https://github.com/music-assistant/models
- https://github.com/music-assistant/client
- https://github.com/music-assistant/home-assistant-addon
- https://github.com/music-assistant/aioslimproto
- https://github.com/music-assistant/aiosonos

Drafts are not reviewed. They stay in the report with the draft badge: a PR that goes back to draft keeps
its last review, and a new draft is carded unreviewed. Marvin's own drafts matter for the reporter
tracking below. Leave out the stable backport bot PRs and every PR listed in `skip`.

A merged or closed PR keeps its entry: set `state` to `merged` or `closed` and `closed_at`. The report
then moves it out of the matrix, except an auto-approved PR, which stays in the auto-approved column for a
week. At the start of every run, drop the entries whose `state` is merged or closed and whose `closed_at`
is more than 30 days old.

## Review workflow

Bot-MArley reviews every PR with Opus and GPT Sol. Don't run your own reviews, request Copilot or run GPT
Sol. Per PR:

- Read Bot-MArley's latest review on the head and its open inline threads. Its "**Requested changes**" list
  and the open threads are the PR's `findings`. Write `tldr`, `summary` and any suggested fix from them and
  the diff.
- If the head has no Bot-MArley review and the latest push is over 15 minutes old, comment
  `@Bot-MArley recheck` on the PR. Do it once per head: skip it when `marley.recheck_head` already equals
  the head, and set it when you post. `recheck` only re-verifies changes it requested earlier: on a PR with
  no Bot-MArley review at all, comment `@Bot-MArley review` instead, also once per head, merge conflicts
  included.
- Categorize the size as S under 50 lines, M 50 to 299, L 300 to 999 or XL 1000 and up. Count changed lines
  of code, without tests, icons, translations and lockfiles.

Judge it as one of:

- `ready`: ready to merge, Bot-MArley approved the current head and none of its threads is open.
- `almost`: almost ready, for example a missing test or something we can easily fix with a single commit.
- `not_ready`: not ready yet, the code really needs attention.

Ready rule: ready to merge needs Bot-MArley's review on the head to be `APPROVED` with zero open
Bot-MArley threads. A finding we judge invalid, pre-existing or a nit still blocks until it's fixed or
answered on its thread. Put such a PR in almost ready with the decline reply or the fix as its suggested fix.

Set `status` on every PR: `attention` when it is Marvin's call to merge, decide or post, `waiting` when the
author or reporter has to act.

## Lab gate

Run the lab-gate skill on a non-draft server PR when it touches risky code: core code (anything outside
`providers/*` and tests) or one of the providers excluded from auto approval below. Once per head, after CI
is green; skip it when `lab.head` already equals the head.

- Don't let it run the full tier 1 gate: a `models/**` change gets `nightly`.
- Store the outcome in `lab`. A `red` result is a blocker naming the failing test and keeps the PR out of
  `ready`. Note `dev-red` and `unreachable` without blocking. Never push fixes to the PR.

## Rules learned on earlier runs

Bot-MArley:

- It reviews new PRs on its own; the first review needs no request.
- Re-review: comment `@Bot-MArley recheck` on the PR, or request it with `gh api --method POST
  repos/music-assistant/<repo>/pulls/N/requested_reviewers -f 'reviewers[]=Bot-MArley'`.
- `APPROVED` is clean. `COMMENTED` means changes requested: the body has a "**Requested changes**" list,
  plus inline review threads.
- Its review on the head is the latest Bot-MArley review whose `commit_id` equals the PR head SHA. Paginate
  reviews with `gh api --paginate`. Busy PRs have over 100 reviews, and the first page shows a stale head.
- Its comments start with a `[!NOTE] This comment was written by Claude and posted by Bot-MArley` header.
- Reviews often land minutes after a push, so re-poll right before you write the state.

Code state:

- Authors push while reviews run. Recheck heads, checks and Bot-MArley reviews right before writing state.
- Fetch PR heads with a leading plus, `git fetch origin +pull/N/head:refs/remotes/pr/N`, or a force-push
  keeps the old ref. Refer to `refs/remotes/pr/N`; short `pr/N` names are ambiguous in the server checkout.
- Run `git merge-tree --write-tree --name-only origin/dev <head>` for every non-draft PR each run, and again
  at the end if dev moved. A stored merge state goes stale as dev moves.
- Check `API_SCHEMA_VERSION` and DB schema numbers against `origin/dev` every time they move, also inside
  suggested patches. After a contributor merges dev, check `git diff origin/dev <head> --
  music_assistant/constants.py` is not empty; they often take dev's number and lose their bump.
- Before flagging a flaw, check whether it already exists on `origin/dev`.
- Validate every suggested patch with `git apply --check <file>` in a throwaway worktree. Hand-written hunk
  counts often come out wrong. Never run `git apply --check` without a file argument: it waits on stdin.
- Server ruff config has `fix=true`, so `ruff check` rewrites files. Run it only in throwaway worktrees.
- Check `reviewDecision` on every PR. An approved PR without auto-merge needs Marvin to queue it.
- Don't put review-status labels on GitHub PRs. Status lives in this report only.

Backport:

- PRs that are ready to merge or auto-approved carry `backport: {rec, why}`. We backport bugfixes that can
  be cherry-picked to stable cleanly or almost cleanly. Judge it from the labels, whether the touched files
  exist on `origin/stable`, and whether the fix is already in the stable backport bot PR.
- Dry-run it with `git merge-tree --write-tree --merge-base $(git merge-base origin/dev <head>)
  origin/stable <head>`. Never cherry-pick in the main checkout.

Tooling:

- If `gh pr list` returns 502 or 504, fall back to `gh api --paginate
  'repos/music-assistant/<repo>/pulls?state=open&per_page=100'`.
- macOS has no `timeout`. Run long read loops in the background and wait for them.
- The state file is JSON with a 1-space indent. Write it back with `json.dumps(state, indent=1,
  ensure_ascii=False)` so the run commits stay small diffs.
- In zsh, `==` inside an inline jq or awk test fails; put such loops in a bash script file.

## SLA and attention

Marvin has a personal SLA of one week. Every run sets `attention_since` on each PR with status
`attention`: the first human, non-bot activity after Marvin's last comment or review, or
`ready_for_review` or `created_at` if he never responded. Take events from `issues/N/timeline` plus
`pulls/N/comments`, because the timeline leaves out inline review replies. Bot-MArley's reviews and
comments are not human activity, and `@Bot-MArley recheck` comments count neither as human activity nor as
Marvin's last comment. His own PRs get none, unless a reporter reply below sets it.

Set `author_replied` when the author of a PR has replied to any of Marvin's questions or comments on it.

Every run, check every open PR, drafts included, for a human comment that waits on Marvin: it mentions
him, replies in a thread he is in, is the author answering him, or asks the reviewers something nobody
answered. Only comments after Marvin's last comment or review count, and his `@Bot-MArley` pings don't.
`~/.claude-teamB/routine-reports/prr-tools/asks.py` lists the candidates in `data/asks.json`. Read them and
judge: a maintainer asking the author, or a status update nobody has to answer, doesn't count. Set
`needs_reply: {at, who, url, summary}` with a one-line summary of what they want from Marvin, set `status`
to `attention` and `attention_since` to the first such comment. Clear `needs_reply` once Marvin has
commented or reviewed after it. The report colours these cards orange, never dims them, even as drafts.

## Attention fields

The attention page (`~/git/dotfiles/routines/attention`) ranks the open cards with status `attention`
or a `needs_reply` together with the asks of the other routines, so this routine doesn't rank them.

Every run sets `action` and `effort` on every attention card. The page has fallbacks for both, but
they only look at the verdict and size, so your call is better. A "reply" on an XL design question is
30 minutes or more, not the fallback 10.

- `action`: what Marvin does next. One of `reply` (someone waits on his answer), `approve` (ready, he
  approves), `merge` (approved already, he queues the merge), `decide` (almost or not ready, he has to
  pick a direction or post findings), `review` (ready but big enough that he should read it himself) or
  `rereview` (his own changes-requested review sits on an old head).
- `effort`: minutes for that action, as an int. Guide values are 5 for an S approval, 10 for M, 20 for
  L, 40 for XL, 10 for a plain reply and 15 to 30 for a decision.

Set `links` on any card where they apply: `[{id, rel, src: "model"}]`, with `id` a canonical id such
as `music-assistant/support#6731`.

- `rel: "fixes"` when the review concludes the PR resolves that issue. Marvin's own PRs say "related
  issue" by convention, so GitHub's closing keywords miss them.
- `rel: "blocked_by"` when the PR has to wait for another PR or issue first.
- Never put an advisory id in a link. This state file is tracked in a public repo.

### Snoozing

`snooze: {at, until, reason}` takes a card off the attention page. `at` is when Marvin snoozed it, in UTC
ISO-8601. `until` is an ISO date and the card comes back on that date. `until: "activity"` keeps it
out until something new happens. Each run, unsnooze a card when its PR got a push, or a comment or
review from someone other than a bot, after `snooze.at`, whatever `until` says. Marvin's own
`@Bot-MArley` pings don't count. Drop snoozes whose date has come. Snoozed cards stay in the matrix.

### Pre-reads

A pre-read prepares a reply or decide card so Marvin can answer in one go. It holds the question, the
options, a recommendation and a draft reply that he can post from the dialog.

After the state is written each run, and before the commit, run
`python3 ~/git/dotfiles/routines/attention/build.py --queue pr-review` and walk its JSON rows from the
top. Take the rows with action `reply` or `decide` whose card has no `preread`, or a stale one.
Stale means `preread.head` differs from `head_sha`, or the PR has a comment or review from someone
other than a bot newer than `preread.at` (the same rule the Post button checks; `asks.py` and
`rc.sh` show them).
Stop at 5 pre-reads per calendar day across all runs. Track the count in the top-level
`preread_budget: {date, used}` and reset `used` when the date changes.

Spawn one Agent subagent per picked card with model `opus`, all in one message so they run in parallel,
in the foreground. Note the UTC time right before you spawn them. Fill in the brief below per card.
Each returns JSON. Store it as `preread` with `at` set to that spawn time in ISO-8601 (so a comment that
lands while the subagent works still counts as newer), `head` set to `head_sha` and `posted: null`,
then rebuild the page. A subagent that returns no usable JSON gets no preread and does not count toward the budget.

```text
You prepare a pre-read for Marvin on music-assistant/<repo>#<n>, <url>, head <head_sha>. Marvin
maintains Music Assistant. He will decide from your pre-read and post your draft reply as is or
edited. You are read-only: don't comment, review, push or change anything on GitHub, and don't check
out branches.

What waits on him: <needs_reply.summary and needs_reply.url, or the next step and blockers>.
Bot-MArley findings: <one line each: id, severity, title, file:line>.

1. Read the PR with gh: the description, the waiting comment and its thread, and the other recent
   comments and reviews. `gh pr view <n> -R music-assistant/<repo> --comments` and
   `gh api repos/music-assistant/<repo>/pulls/<n>/comments` cover both.
2. Read the code. `gh pr diff <n> -R music-assistant/<repo>` gives the diff against its base. For
   whole files, run `git fetch origin +pull/<n>/head:refs/remotes/pr/<n>` in
   /Users/marvin/git/music-assistant/<repo> and use `git show refs/remotes/pr/<n>:<path>`.
3. Work out the real question for Marvin, the realistic options and the one you would pick.

Return only this JSON object, nothing around it:
{"question": "one sentence", "options": ["2 to 4 short options"],
 "recommendation": "the option you pick and why, in one or two sentences",
 "draft_reply": "the comment Marvin would post"}

Write the draft reply in Marvin's voice. Short and to the point, human, no filler and no padding
praise. It starts with exactly these two lines and a blank line:
> [!NOTE]
> This comment was written by Claude on Marvin's behalf
Address the person by @handle. No em dashes. Link files and lines when it helps, as
https://github.com/music-assistant/<repo>/blob/<head_sha>/<path>#L<line>. Never promise a release
or a date.
```

### Posted replies

The Post button in a dialog sends the draft, or Marvin's edit of it, to `report_server.py`, which posts
it with `gh pr comment` and appends `{at, action: "post", repo, n, hash, url, edited, body}` to
`~/.claude-teamB/routine-state/pr-review-actions.jsonl`. `body` is only there when he edited the
draft. The server refuses when the page is stale, the draft was posted already, the PR is closed or
merged, its head moved past `preread.head`, or a person commented or reviewed after `preread.at`.

At the start of every run, fold in every log entry whose hash isn't recorded on its card yet: set
`preread.posted: {at, url, hash, body}` (`body` only when the entry has one, so the page shows what was
really posted), clear `needs_reply` and judge `status` again. Usually the
author has to act next.

The button only works when the page comes from the `local.routine-reports` LaunchAgent, which runs
`report_server.py`; a page opened from disk can copy but not post. After changing `report_server.py`,
restart it with `launchctl kickstart -k gui/$(id -u)/local.routine-reports`.

## Reporter replies on my PRs

For every open PR authored by MarvinSchenkel, drafts included, find the support issues it links to in the
PR body and comments, for example music-assistant/support#N. Each run, check those issues for a non-bot
comment posted after Marvin's last comment there. If you find one, mark the PR as needs my attention with
`attention_since` set to that comment's time, and add a short summary of the reply to the PR's
`reporter_reply`. Say it in the run summary too, for example "reporter confirmed the fix" or "reporter
reports a new problem". When Marvin asked for a test and nobody has replied after 7 days, mention it in
the run summary. Track this per PR in `support`.

## Auto approval

You are not allowed to auto approve any PRs in the server repository. Maintainers have the ability to merge PRs by asking Bot MArley after he has approved the PR. 

Auto approval for other repositories: only dependabot or bump PRs that are safe to merge. Our own packages,
for example music-assistant-models, can be auto-merged. Bot pin bumps in the server repo are approved and
merged by the repo's own workflow: card them as ready and waiting.

When you auto-approve the PR:

- Approve it with a message that thanks the original author by tagging their GitHub handle with a fun
  emoji, for example "Thanks @OzGav, looks good to me :raised_hands:". Start it with `> [!NOTE] This
  comment was written by Claude on Marvin's behalf` and say it was auto-approved because Bot-MArley's review
  was green.
- Turn auto-merge on with `gh pr merge --squash --auto`. The server repo uses a merge queue, so the command
  prints that the merge strategy is set by the merge queue and `autoMergeRequest` reads null. The PR still
  merges; don't retry, check its state on the next run.
- CI re-runs and the PR merges when everything is green.
- Record `auto_approved: {at, note}` on the entry.

Marvin cannot approve his own PRs, so never auto-approve them.

## Report

`build.py` builds the report page from the state file:

```sh
mkdir -p ~/.claude-teamB/routine-reports
python3 ~/git/dotfiles/routines/pr-review/build.py ~/git/dotfiles/routines/state/pr-review.json \
  --full ~/.claude-teamB/routine-reports/pr-review.html
```

- The report goes to `~/.claude-teamB/routine-reports/pr-review.html`, outside git on purpose. It
  holds every review untrimmed. The `local.routine-reports` LaunchAgent (`routines/launchd/`, installed by
  `install.sh`) serves that folder on `http://127.0.0.1:8765`, and the report stays open in this thread's
  side panel. Marvin can also run `open ~/.claude-teamB/routine-reports/pr-review.html`.
- After the build, refresh the side panel: `t3_preview_list`, then `preview_navigate` the tab whose URL
  starts with `http://127.0.0.1:8765/pr-review.html` to `http://127.0.0.1:8765/pr-review.html?run=<YYYYMMDDHHMM>`
  with the run time; the query keeps the panel from showing the cached previous report. With no such tab,
  `preview_open` that URL. If the URL doesn't answer, run
  `launchctl kickstart -k gui/$(id -u)/local.routine-reports` and retry once; if it still fails, say so in
  the chat summary. A `render` reply refreshes the panel the same way.

Don't edit the page by hand. If the layout has to change, change `build.py` and tell Marvin; run
commits still hold only the state file.

The report shows:

- A matrix with the status on the Y axis, needs my attention or waiting for user, and the ready state on the
  X axis: ready to merge, almost ready, not ready yet, plus one extra column for auto-approved PRs so Marvin
  can keep track of them. That column only shows PRs auto-approved in the last week.
- SLA colouring: a card that has waited on Marvin for a week or more is red.
- Action colouring: a PR that requires my response, regardless of its merge state, needs to be coloured orange. Examples are:
    - User has asked a question that requires my response
    - User has replied to one of my comments
    - PR is stuck on something only a maintainer can do, e.g. adding a 'dependency reviewed' label
- Badges on the cards, only in the report, never as GitHub labels: size, draft, user replied, reporter
  replied, backport recommended on ready and auto-approved PRs, yours, new review, failing CI, stacked, and
  days waiting on Marvin.
- Per PR, in a dialog that opens when Marvin clicks its card or opens the page at
  `pr-review.html#pr-<repo>-<number>` (the attention page links there), ordered by what he needs first: a next-step
  panel (one line on what to do, up to three blockers, and the reply commands as copy chips), one-word
  pills for CI, merge, Bot-MArley, lab and backport, the `tldr`, then the findings one line each with
  their id `f1`, `f2` and so on so Marvin can reply `post <pr> f2`. Set `model` on every finding to
  Bot-MArley. Everything else (this run's changes, full CI/merge/Bot-MArley notes, the review notes in
  `summary`, suggested fix, prompt, comments) sits under a collapsed "More details". Keep `blockers` short
  and actionable, since they are the first thing he reads.
- For a card with a `preread`: a pre-read block right after the next-step panel with the question,
  options and recommendation, and the draft reply in an editable box with Copy and Post. Once posted it
  shows the reply read-only with a link to the comment.
- For almost ready: your suggestion to fix the small outstanding thing, the patch as a coloured diff, and
  the prompt for a fix session with the necessary context and instructions, readable in place and with a
  copy button.
- Nothing below the matrix. Merged and closed PRs show up in the chat summary of the run that saw them.

Fill `marley` and `waiting_on` on every PR so the pills and the next-step panel say something useful.

Set `changed_now` on every PR this run touched, as a short reason: `new`, `reviewed`, `pushed`, `merged`,
`closed`, `auto-approved`, `reporter replied`, `author replied`, `drafted`, `ready for review`,
`conflict`, `CI failing`. Clear it on the rest at the start of the run. A reviewed PR may leave it empty;
`reviewed_now` marks it.

The report must always be up to date and combined with the previous runs. If an earlier run tagged a PR
almost ready and Marvin hasn't acted on it, it stays. A PR only leaves the matrix when it is merged or
closed, except an auto-approved PR, which stays in its column for a week.

Write `run_note` before building: two to four sentences on what changed this run. The page shows it.

If `build.py` exits with a budget error, say so in the chat summary.

## Chat summary

The last step of every run is the attention build, after the commit:

```sh
python3 ~/git/dotfiles/routines/attention/build.py --source pr-review
```

Then end the turn with a short chat summary of what this run changed: new, reviewed, merged and closed
PRs, reporter replies, test asks that passed 7 days without an answer, what was auto-approved, and
anything that failed or was skipped. Link every PR to its GitHub page. Don't list the cards that wait on
Marvin; the attention page ranks them. Paste the attention build's output: its `+ Act` lines, then its
last `attention:` line. Always end the summary with a clickable link to the matrix,
`[Open the PR matrix](http://127.0.0.1:8765/pr-review.html?run=<YYYYMMDDHHMM>)`, since the side panel
tab isn't always visible to Marvin.

## Replies

Marvin answers in this thread. Handle each reply straight away; don't wait for the next run. The
attention thread forwards the commands Marvin gives on the attention page here as plain messages, in
the same grammar; handle them like his own replies. A forwarded command may name a PR by its attention id,
such as `server#7498` or `frontend#3004`: `server#<n>` is the server PR `<n>`, any other id is already
`<repo>#<n>`. `<pr>` is
the number for a server PR, with or without `#`, and `<repo>#<n>` for the other repos, the same labels the
page shows. One reply can hold several commands, for example `post 7045 f1 f3, approve 7130`.

- `post <pr> f<n> [f<m> ...]`: post those findings as review comments. Skip findings that already sit
  on a Bot-MArley thread. When the finding's line is part of
  the PR diff, post it inline on that line of the current head; otherwise post a PR comment. Keep it short
  and in Marvin's style, starting with `> [!NOTE] This comment was written by Claude on Marvin's behalf`.
  Record `posted: {at, url}` on the finding.
- `fix <pr>`: commit the PR's `suggested_fix.patch` on top of the head and push it to the PR branch, only if
  the PR head still equals `head_sha`; otherwise say so and offer `review <pr>`. Apply-check it in a
  throwaway worktree first, commit as Marvin Schenkel <marvinschenkel@gmail.com>, push, and reply on the PR
  in one or two sentences with the same NOTE line. When `git push` to a contributor's fork returns 403,
  use `gh api graphql` with `createCommitOnBranch` and `expectedHeadOid` pinned to the head. Record
  `pushed: {at, sha}` on the suggested fix.
- `approve <pr>`: approve with a short thank-you to the author and the NOTE line, then turn auto-merge on
  as in auto approval. Not possible on Marvin's own PRs; say so.
- `chip <pr>`: start a fix session. Call `t3_thread_launch` with workspaceStrategy `{"type":"root"}` and
  title "Fix: <short PR title>". T3 cannot make worktrees for this project because the workspace root is
  not a git repo, so the message tells the new thread to work inside
  `/Users/marvin/git/music-assistant/server`, or the PR's own repo next to it, create a Claude worktree
  there with `EnterWorktree` or `git worktree add .claude/worktrees/<slug> -b fix/<slug> origin/dev`, and
  start with the gogogo skill. When the fix belongs on the PR itself, the worktree starts from
  `refs/remotes/pr/N` in place of `origin/dev`. The message carries the PR number and URL, the head sha, the
  findings and the PR's prepared `prompt`. Link the launched thread in your reply and record it in
  `fix_thread`.
- `prompt <pr>`: print the prepared prompt in a code block.
- `show <pr>`: print the full review in chat: tldr, summary, findings with their bodies and the patch.
- `review <pr>`: review the PR again now with the full workflow above.
- `snooze <pr> [Nd|YYYY-MM-DD]`: set `snooze` with `at` now and `until` that many days from today, or
  that date. The default is 3d. Put the reason in `reason` when Marvin gives one.
- `later <pr>`: set `snooze: {at: now, until: "activity"}`. The card returns on a push or a new comment
  after `at`.
- `unsnooze <pr>`: remove `snooze`.
- `skip <pr>` and `unskip <pr>`: add the PR to `skip` with a one-line reason, or take it out. A skipped PR
  stays out of the report until unskipped.
- `render`: build the page from the current state.
- Anything else: answer from the state file and re-query GitHub when needed.

A reply that changes the state writes it back and commits it the same way, with the message
`pr-review: reply <YYYY-MM-DD HH:MM>`. Never push. Every handled reply, forwarded or not, ends by
rebuilding this routine's page, then running the attention build as in the chat summary, and pasting
its last line into the answer. After a forwarded command add `--handled`, which clears its "sent" marker on the attention page.

## State file shape

```json
{
  "thread_id": "<this thread's id>",
  "scheduled_task_ids": ["<one id per schedule, 07:00 to 17:00>"],
  "last_run": "2026-10-21T08:25:00+02:00",
  "dev": "03ee9a687",
  "run_note": "two to four sentences shown under the title",
  "skip": { "server#6184": "why it stays out" },
  "preread_budget": { "date": "2026-10-21", "used": 2 },
  "prs": [
    {
      "repo": "server", "number": 7045, "state": "open", "closed_at": null,
      "title": "", "author": "", "url": "", "draft": false,
      "verdict": "ready | almost | not_ready", "assessment": "approve | comment | request_changes",
      "status": "attention | waiting", "attention_since": "2026-10-20T13:12:02Z",
      "waiting_on": "you | author | reporter | OzGav review | Bot-MArley",
      "size": "S", "code": 10, "add": 29, "del": 6,
      "ci": "", "ci_fail": false, "merge_state": "", "head_sha": "babefc242",
      "core_touched": false, "providers_touched": ["sync_group"], "stacked": false,
      "tldr": "5 to 6 lines max", "summary": "longer review notes", "whats_new": "since the last run",
      "blockers": [""],
      "findings": [
        { "model": "Bot-MArley", "severity": "CRITICAL | PROBLEM | SUGGESTION | NIT",
          "file": "", "line": 0, "title": "", "detail": "", "fix": "", "posted": { "at": "", "url": "" } }
      ],
      "unaddressed_comments": [ { "author": "", "at": "", "url": "", "summary": "" } ],
      "marley": { "verdict": "approved | changes | none", "reviewed_head": true, "open_threads": 0,
                  "review_url": "", "note": "", "recheck_head": "babefc242" },
      "lab": { "head": "babefc242", "areas": ["queue"], "result": "green | red | dev-red | unreachable | skipped | nightly",
               "run_id": "", "note": "" },
      "suggested_fix": { "description": "", "patch": "unified diff", "pushed": { "at": "", "sha": "" } },
      "prompt": "fix session prompt",
      "backport": { "rec": true, "why": "" },
      "auto_approved": { "at": "2026-10-21 07:20 CEST", "note": "" },
      "author_replied": { "at": "", "url": "", "summary": "" },
      "needs_reply": { "at": "", "who": "", "url": "", "summary": "" },
      "reporter_reply": { "issue": "support#6731", "author": "", "at": "", "url": "", "summary": "" },
      "support": [ { "issue": "support#6731", "my_last_comment_at": "", "test_asked_at": "" } ],
      "fix_thread": "link to the launched thread",
      "action": "reply | approve | merge | decide | review | rereview", "effort": 10,
      "links": [ { "id": "music-assistant/support#6731", "rel": "fixes | blocked_by", "src": "model" } ],
      "snooze": { "at": "2026-10-21T06:30:00Z", "until": "2026-10-24 | activity", "reason": "" },
      "preread": { "at": "2026-10-21T06:30:00Z", "head": "babefc242", "question": "", "options": [""],
                   "recommendation": "", "draft_reply": "", "posted": { "at": "", "url": "", "hash": "", "body": "" } },
      "related_prs": ["#6801 merged base"],
      "reviewed_now": false, "changed_now": "pushed", "reviewed_at": "2026-10-21 07:45 CEST"
    }
  ]
}
```

`posted`, `pushed`, `author_replied`, `needs_reply`, `reporter_reply`, `support`, `fix_thread`, `snooze` and
`preread` are null or absent until they apply, `links` is empty or absent until one applies. `action`
and `effort` are set on every attention card. Set `reviewed_now` only on PRs reviewed in the current run and clear it on the rest.
`waiting_on` is a short string for the next-step panel. Entries with `state` merged or closed
and `closed_at` more than 30 days old are dropped at the start of a run.
