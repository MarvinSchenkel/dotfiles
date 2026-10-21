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
  artifact.
- Secrets never go in this repo. Routines source `~/.claude-teamB/ma-routines.env` (mode 600).

How a run works

1. The scheduler posts the run prompt into the routine's thread.
2. The routine reads its SKILL.md and state file, does the work, writes state, commits.
3. It writes the full report to `~/.claude-teamB/routine-reports/<name>.html` (open it in a browser) and
   renders a compact digest inline with `html_render`, then ends with a short chat summary. The digest
   exists because `html_render` takes the page as a tool argument, so every character costs output tokens.
4. Anything that used to be a button is a reply in the thread: "post 3", "fix 2", "dismiss cs-171".
   The thread's agent handles the reply straight away; a fix session is a thread launched with
   `t3_thread_launch` in a worktree.

Schedules (T3 scheduler, local time)

| routine | cadence | thread |
|---|---|---|
| triage-ma-nightly | daily 05:00 | one task |
| pr-review | hourly 07:00 to 17:00 Mon to Fri | eleven fixed-time tasks, one per hour |
| issue-triage | xx:30, 07:30 to 17:30 Mon to Fri | eleven fixed-time tasks, one per hour |
| security-advisories--code-scanning | 07:30 Mon and Wed | one task |

Thread ids and task ids live in each routine's state file. T3's fixed-time schedule takes one time of day,
hence one task per hour for the two hourly routines.

The scheduler runs inside T3 Code, so routines only fire while the app is open, same as the desktop.

The `local.routine-reports` LaunchAgent (`launchd/`, installed by `../install.sh`) serves
`~/.claude-teamB/routine-reports` on `http://127.0.0.1:8765`, so a routine can keep its full report open in
its thread's side panel.
