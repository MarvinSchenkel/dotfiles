---
name: lab-deep
description: Daily deep run of the Music Assistant end-to-end lab (every virtual player role, every frozen streaming account set) with a digest posted inline in this thread
---

# Lab deep run

You are the routine thread for this job. Each scheduled run arrives as a new turn in this thread.
Read `~/git/dotfiles/routines/state/lab-deep.json` first, then do the run below, then write the
state back and commit it in `~/git/dotfiles` as Marvin (marvinschenkel@gmail.com) with the message
`lab-deep: run <YYYY-MM-DD>`. Never push. Never create issues, PRs or comments from this thread.

## Inputs

- The lab CLI runs from the Mac: `/Users/marvin/git/music-assistant/lab/bin/lab`. It syncs the
  local `lab/` checkout to the VM and runs `labctl` there over `ssh lab`.
- `lab/README.md` (areas, what each check covers), `lab/docs/runbook.md` ("Reading a failed run").
- `known_red` in the state file: tests that are red on `dev` for a known reason, with the date and
  the note. They stay in the digest, marked known, and never count as a regression.

## Run

1. `ssh lab true` and `lab status`. If the VM or labd does not answer, post one line saying so and stop.
2. `lab run --ref dev --deep 2>&1 | tee /tmp/lab-deep-dev.log`. It starts one tier 1 run over every
   deep role (`deep` marker, no rerun) and then one tier 2 run per frozen account set; every run prints
   `run <id>: ...`. Collect the run ids from the output.
3. On Mondays also `lab run --ref stable --deep`, same handling, reported in its own section.
4. `lab summary <id> ...` over the collected ids, and `lab flakes` for the gate reruns of the last
   30 days.
5. Hardware: the bench (`hw` marker) is not part of `--deep` until the hardware tier lands
   (`.claude/plans/ma-lab-hardware/plan.md`). Say "hw: not run" in the digest. Once `lab run` accepts
   `--devices`, check the bench plug through the registry's HA entity first and skip hw with that reason
   when it is off; never switch the plug yourself.

## Digest

Post the digest as a message in this thread, nothing else. Green everywhere: one line with the ref,
the server sha, the run ids and the total time. Otherwise:

1. One line per ref: ref, server sha, runs, total time.
2. Per area: passed/total, and for every failed test its checkpoint and the issue ids `lab summary`
   prints. Mark tests listed in `known_red` as known. Tier 2 areas are `music_<provider>`.
3. Flakes from `lab flakes` that are new since the previous run.
4. For a new red, the first lines of the failure from `/srv/lab/runs/<id>/junit.xml` and your read on
   whether it is the server or the lab (a test that fails the same way on `dev` and on the previous
   day's run is a dev regression; a capture or fixture error is the lab's). No fixes from this thread.
5. The footer: "Reply `investigate <test>` to start a session on a red, `known <test>` to list it as a
   known red."

## State

`{"last_run": "<date>", "runs": {"dev": [ids], "stable": [ids]}, "known_red": [{"test": "...",
"since": "<date>", "note": "..."}], "last_flakes": [...]}`. Keep `known_red` current when Marvin
replies `known <test>`; drop an entry once the test passes two days in a row and say so in the digest.
