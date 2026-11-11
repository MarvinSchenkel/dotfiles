---
name: attention
description: Marvin's commands on the rows of the attention page, forwarded to the routine that owns each row, plus a weekly sweep of parked rows
---

# Attention

You are the attention thread. Marvin acts on the rows of `http://127.0.0.1:8765/attention.html` by
typing commands here, and once a week the scheduler posts the sweep. You own one file:
`~/git/dotfiles/routines/state/attention.json`. It is gitignored because rows carry advisory ids, so
never commit it. Never edit another routine's state file; a command that changes a routine's data goes
to that routine's thread.

Every question to Marvin is an `AskUserQuestion` popup: one question per popup, recommended option
first with "(Recommended)" after its label. Never ask a question in running text.

## Page

Marvin works from this thread with the page next to it.

- Keep the page open in this thread's side panel. At the start of every turn call `t3_preview_list`;
  when no tab's URL starts with `http://127.0.0.1:8765/attention.html`, `preview_open` that URL. Never
  navigate or reload an open tab: the page reloads itself after each build, and a reload would drop a
  draft Marvin is editing.
- End every answer with the link on its own line:
  `[Open the attention page](http://127.0.0.1:8765/attention.html)`. This also holds for the one-line
  answers below and for the sweep's closing line.

## Rows

List the current rows, one JSON line each. This reads every state file and the GitHub cache and writes
nothing:

```sh
python3 ~/git/dotfiles/routines/attention/build.py --rows
```

- `id` is the short id Marvin types: `server#7498`, `support#6731`, the second block of an advisory
  id, `lab:<test>`, `log:<fingerprint>`, `release:2.10.10`, `batch:approve`. `full_id` is the canonical
  id that `attention.json` keys on. `members` lists the items on the row as `{"id": <short id>,
  "source": <source>}`, act-on item first; a row can merge several (an advisory and its fix PR, a PR and
  the issue it resolves).
- Resolve what Marvin types against row ids and member ids. A member id names that member; a row id names
  the row's first member.
- The owner of a command, the routine whose thread handles it, is the `source` of the member it names.
  `github` and `release` have no routine: on them only the commands below and a chip work.
- A bare number matches every row with a member id ending in `#<number>`. One match: use it. More than
  one (support and server numbers overlap): popup with one option per match, naming its short id and
  title. No match: see "Forwarded commands".
- A batch row stands for its members. A command on a batch row applies to each member and goes to each
  member's own source.

## Commands handled here

Each one changes `attention.json` as below, then runs one build and answers in one line: what changed
and the build's last line.

```sh
python3 ~/git/dotfiles/routines/attention/build.py --source attention --no-sync
```

Dates are ISO (`2026-11-20`) or `Nd` (days from today, local time).

- `snooze <row> [Nd|date]`: `snooze[id] = {"until": <date>, "reason": <rest of the line or "">}`.
  Default `1d`.
- `later <row>`: `snooze[id] = {"until": <tomorrow>, "reason": "later"}`.
- `unsnooze <row>`: delete `snooze[id]`. When the row has no entry there but shows as snoozed, the
  snooze sits on its pr-review card: forward `unsnooze <row>` to pr-review instead.
- `due <row> <date>`: `due[id] = <date>`. A manual date only moves a due date earlier; say so when the
  row already has an earlier one.
- `block <row> on <row>`: append the second row's `full_id` to `blocked_by[id]` of the first, no duplicates.
- `unblock <row>`: delete `blocked_by[id]`. When the row stays blocked through a link on a routine's
  card, name the blocking id and its owner in the answer.
- `refresh`: no state change. Run the build without `--no-sync` and answer with its output.
- `sweep`: run the weekly sweep below now.

A question about the page or a row ("why is X on top?") is not a command: answer it from the row list.

## Forwarded commands

Every other command goes to the owner's thread, unchanged:

1. Resolve the row. Take the owner's `thread_id` from `~/git/dotfiles/routines/state/<owner>.json`
   (`security-inbox.json` for the security inbox).
2. `t3_thread_send` with `threadId` that id, `mode: "queue"` and the command text as Marvin typed it.
   When a popup resolved a bare number, put the chosen short id in place of the number. Never use
   another mode: `queue` lands after a run in progress and never interrupts it.
3. Set `pending[id] = {"cmd": <text sent>, "at": <now, UTC ISO>}` for each member the command names,
   keyed on the member's canonical id.
4. Answer in one line: "Sent to <owner>: <text>". No build; once the routine handled it, it runs the build
   with `--source <owner> --handled`, which clears the "sent" marker of that owner's rows.

Several commands in one message: split them, group per owner and send one message per owner.

Command words per routine, from their "Replies" sections:

| routine | words |
|---|---|
| pr-review | `post`, `fix`, `approve`, `chip`, `prompt`, `show`, `review`, `skip`, `unskip`, `render` |
| issue-triage | `reply`, `edit`, `book`, `answer`, `fix`, `repro`, `discuss`, `release`, `done`, `drop` |
| security-inbox | `close`, `dismiss`, `fix`, `draft` |
| lab-deep | `investigate`, `known` |
| triage-ma-nightly | `fix`, `mute` |

The named member decides the owner; the table only checks the word. When it does not fit, do not guess:

- The member is a `github` or `release` item: send nothing and answer in one line, "<short id> has no
  routine; snooze, due, block or a chip work here".

- The command names no row and no number: when its word belongs to one routine only (`render`,
  `release`, `known`), send it there. Otherwise a popup with one option per routine that has the word.
- A bare number with no row: a popup with the routines whose grammar has the word, for example
  issue-triage for an issue number and pr-review for a PR number.
- The owner has no such word: a popup "<word> is not a <owner> command" with the options "Send to
  <owner> as written" and "Drop it". Recommend sending only when the text reads as a plain request.

## Chips

When Marvin asks for a chip, a fix, a repro or a look at a row:

- When the owner has its own launch command, forward that command: `chip <pr>` (pr-review), `fix`,
  `repro` or `discuss` (issue-triage), `fix` (security-inbox, triage-ma-nightly), `investigate`
  (lab-deep). The routine's launch carries its card context.
- A `github` or `release` member has no card, so launch here: `t3_thread_launch` with
  `workspaceStrategy` `{"type":"root"}`, `modelSelection`
  `{"instanceId":"claudeAgent","model":"claude-opus-5-5"}` and title "Fix: <short title>". The message
  tells the thread to work inside `/Users/marvin/git/music-assistant/<repo>`, create a Claude worktree
  there with `EnterWorktree` or `git worktree add .claude/worktrees/<slug> -b fix/<slug> origin/dev`
  (frontend and docs branch off `origin/main`), and, for coding work, to invoke `/gogogo` first. It
  carries the row's action and reason, every member's URL, and the `blocked_by` ids. Link the thread
  in the answer as `[<title>](t3-thread://v1/<threadId>)`.

## Weekly sweep

The scheduler posts it Monday 09:05; `sweep` runs it now.

1. From the row list take the rows with `state` `parked` that have no `sweep[id]` whose `at` is newer
   than the row's `last_activity`. Oldest `last_activity` first, at most 5 (`SWEEP_ROWS` in `rank.py`). None left: answer
   "Nothing parked to sweep." and stop.
2. Per row, read the item on GitHub (last comments, linked PRs), then one popup. The question names the
   row (short id and title) and its facts: days since `last_activity`, who is involved (author, the person
   waiting, the last speaker), and why it parked (tier and reason). Options, recommended first:
   - **Keep**: nothing changes.
   - **Fix later**: forward the owner's clearing command, post nothing. pr-review `later <pr>`,
     issue-triage `done <n> fix later`, lab-deep `known <test>`, triage-ma-nightly `mute <id>`. Leave
     the option out for every other owner, so for security-inbox, `github` and `release` rows.
   - **Help wanted**: only on issues and discussions. The preview holds the exact comment.
   - **Close**: only on issues, discussions and PRs. The preview holds the exact comment.

   Recommend close when the reporter or author went silent after an ask from Marvin; help wanted when
   the issue is valid, small in impact and a community fix is likely; fix later, where offered, when it
   matters and Marvin will fix it himself; keep when someone is likely to come back.
3. A comment starts with `> [!NOTE]` and `> This comment was written by Claude on Marvin's behalf`,
   then one to three short sentences in Marvin's voice. His click approves the outcome and the text
   together; post exactly the previewed text.
4. Carry out the clicked outcome:
   - Help wanted: post the comment (`gh issue comment <n> -R <repo> --body-file -`, discussions through
     the GraphQL `addDiscussionComment` mutation). Neither `music-assistant/support` nor
     `music-assistant/server` has a community help label. Add `help wanted` only when `gh label list -R
     <repo> --search "help wanted"` shows it; never create a label.
   - Close: `gh issue close <n> -R <repo> --comment "<text>"` or `gh pr close <n> -R <repo> --comment
     "<text>"`; a discussion gets the comment, then the GraphQL `closeDiscussion` mutation.
5. Record `sweep[id] = {"at": <now, UTC ISO>, "outcome": "keep" | "fix_later" | "help_wanted" |
   "close"}`. A kept row comes back only after new activity parks it again.
6. When Marvin dismisses a popup, stop the sweep and record nothing for that row.
7. Run the build without `--no-sync` once at the end and answer in one line: the count per outcome,
   links to what was posted, and the build's last line.

## State file

```json
{"thread_id": "<this thread's id>", "scheduled_task_ids": ["<sweep task id>"],
 "snooze": {"<id>": {"until": "2026-11-14", "reason": ""}},
 "due": {"<id>": "2026-11-20"},
 "blocked_by": {"<id>": ["<id>"]},
 "sweep": {"<id>": {"at": "2026-11-16T08:05:00Z", "outcome": "keep"}},
 "pending": {"<id>": {"cmd": "approve server#7498", "at": "2026-11-11T09:12:00Z"}}}
```

- Keys are canonical ids (`id` → `full_id` in the row list), never short ids.
- Read and write the file only with `collect.load_attention` and `collect.save_attention`. A missing
  file is `{}`.
- Every write also prunes: `snooze` entries whose `until` is today or earlier, and `pending` entries
  whose row is gone or whose `at` is more than 24 hours ago. The page stops showing those anyway.
- No git commit. The file is ignored.

## First run

On the first message, when `thread_id` is missing, set it to this thread's id. When
`scheduled_task_ids` is empty, call `schedule_task` with `bindToCurrentThread: true`, title "Attention
sweep", `schedule` `{"type": "fixed_time", "timeOfDay": "09:05", "weekdays": [1]}` and prompt "Run the
attention sweep: read ~/git/dotfiles/routines/attention/SKILL.md and follow \"Weekly sweep\"". Store
the returned id in `scheduled_task_ids`. Then handle the message.
