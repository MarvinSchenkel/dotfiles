# Routines

Scheduled jobs that used to be Claude Desktop routines. Each one is a T3 Code scheduled task bound to
one long-lived thread on the "Claude 2" provider instance (the team seat), inside the music-assistant
project, so the thread's cwd is the workspace root and it shares the auto-memory under
`~/.claude/projects/-Users-marvin-git-music-assistant/memory`.

Layout

- `<name>/SKILL.md` is the routine prompt. The scheduled task's prompt only says "Run the <name> routine:
  read <path to SKILL.md> and follow it for this run", so edits here take effect on the next run without
  touching the scheduler. `build.py` next to it turns the state file into the report pages.
- `state/<name>.json` is the state carried from run to run. The routine reads it at the start of a run,
  merges, writes it back and commits it here. This replaced the JSON that lived inside the claude.ai
  artifact. Two state files are gitignored and never committed, because they hold advisory details:
  `security-inbox.json` and `attention.json`.
- Each state file has one writer: its own routine thread.
- Secrets never go in this repo. Routines source `~/.claude-teamB/ma-routines.env` (mode 600).

How a run works

1. The scheduler posts the run prompt into the routine's thread.
2. The routine reads its SKILL.md and state file, does the work, writes state, commits.
3. It writes the full report to `~/.claude-teamB/routine-reports/<name>.html` (open it in a browser) and
   ends with a short chat summary. lab-deep and triage-ma-nightly also render their report inline with
   `html_render`; lab-deep renders a compact digest because `html_render` takes the page as a tool
   argument, so every character costs output tokens.
4. Anything that used to be a button is a reply in the thread: "post 3", "fix 2", "dismiss cs-171".
   The thread's agent handles the reply straight away; a fix session is a thread launched with
   `t3_thread_launch` in a worktree.
5. Its last step is `python3 ~/git/dotfiles/routines/attention/build.py --source <name>`, which rebuilds
   the attention page. The same build ends every reply that changes the routine's state.

Attention

`attention/` is one ranked list of Marvin's asks across all routines, served as
`http://127.0.0.1:8765/attention.html`. `SKILL.md` is the prompt of the attention thread, `gh_sync.py`
caches the GitHub facts, `collect.py` reads every routine's state and the cache, `rank.py` holds the
rules and `build.py` writes the page. The attention thread has no run schedule of its own apart from a
weekly sweep of parked rows on Monday 09:05; the routines rebuild the page.

The attention thread takes every command. It handles snooze, due dates and manual blocks itself and
writes them to `state/attention.json`. A command that changes a routine's data it forwards to that
routine's thread as a plain message, with `t3_thread_send` in queue mode, so a run in progress never loses
a write. The routine handles it with its own reply grammar and rebuilds its page and the attention page.

Schedules (T3 scheduler, local time)

| routine | cadence | thread |
|---|---|---|
| triage-ma-nightly | daily 05:00 | one task |
| pr-review | hourly 07:00 to 17:00 Mon to Fri | eleven fixed-time tasks, one per hour |
| issue-triage | xx:30, 07:30 to 17:30 Mon to Fri | eleven fixed-time tasks, one per hour |
| security-advisories--code-scanning | 07:30 Mon and Wed | one task |
| attention | Mon 09:05, weekly sweep only | one task |

Thread ids and task ids live in each routine's state file. T3's fixed-time schedule takes one time of day,
hence one task per hour for the two hourly routines.

The scheduler runs inside T3 Code, so routines only fire while the app is open, same as the desktop.

The `local.routine-reports` LaunchAgent (`launchd/`, installed by `../install.sh`) serves
`~/.claude-teamB/routine-reports` on `http://127.0.0.1:8765`, so a routine can keep its full report open in
its thread's side panel. The server is `report_server.py`; it also takes the issue-triage board's Post button,
posts the draft with `gh` and logs it to `~/.claude-teamB/routine-state/issue-triage-actions.jsonl`.
