---
name: lab-deep
description: Daily deep run of the Music Assistant end-to-end lab (every virtual player role, every frozen streaming account set) with an HTML report in the side panel and a digest inline in this thread
---

# Lab deep run

You are the routine thread for this job. Each scheduled run arrives as a new turn in this thread.
Read `~/git/dotfiles/routines/state/lab-deep.json` first, then do the run below, then write the
state back and commit it in `~/git/dotfiles` as Marvin (marvinschenkel@gmail.com) with the message
`lab-deep: run <YYYY-MM-DD>`. Never push. Never create issues, PRs or comments from this thread.

## Inputs

- The lab CLI runs from the Mac: `/Users/marvin/git/music-assistant/lab/bin/lab`. It syncs the
  local `lab/` checkout to the VM and runs `labctl` there over `ssh lab`.
- `lab/docs/pr-gate.md` (areas, what each check covers), `lab/docs/runbook.md` ("Reading a failed
  run").
- `known_red` in the state file: tests that are red on `dev` for a known reason, with the date and
  the note. They stay in the report, marked known, and never count as a regression.

## Run

1. `ssh lab true` and `lab status`. If the VM or labd does not answer, post one line saying so and stop.
2. `lab run --ref dev --deep 2>&1 | tee /tmp/lab-deep-dev.log`. It starts one tier 1 run over every
   deep role (`deep` marker, no rerun) and then one tier 2 run per frozen account set; every run prints
   `run <id>: ...`. Collect the run ids from the output.
3. On Mondays also `lab run --ref stable --deep`, same handling, reported in its own section.
4. `lab summary <id> ...` over the collected ids, and `lab flakes` for the gate reruns of the last
   30 days.
5. Hardware (bench): `--deep` does not take devices, so the bench is a separate run. First
   read the bench plug (entity in the state file under `bench.power_entity`; an HA automation powers it
   on workdays 07:15 to 19:00, never switch it yourself):

   ```
   ssh -i ~/.ssh/claude_ha_ed25519 -o BatchMode=yes marvin@192.168.1.80 'sudo -i python3 -c "import os,json,urllib.request; r=urllib.request.Request(\"http://supervisor/core/api/states/switch.ma_lab_test_bench\", headers={\"Authorization\": \"Bearer \"+os.environ[\"SUPERVISOR_TOKEN\"]}); print(json.load(urllib.request.urlopen(r, timeout=5))[\"state\"])"'
   ```

   Prints `on` or `off`. When `on`: `lab run --ref dev --providers devices 2>&1 | tee
   /tmp/lab-deep-hw.log`, collect its run id and include it in the summary step; its tests report under
   `hw` with the `device` property. When `off`, unreachable, or the lab answers that the registry has no
   devices: do not run it, and set `hw_skipped` to the reason in the state; the report shows `hw: skipped (<reason>)`.

## Report

The report is an HTML page built from the runs' JUnit files by `build.py` next to this file, plus a
compact digest of it rendered inline. Change the layout in `build.py`, never by hand.

1. Copy the run artifacts of this run's ids (tier 1, tier 2, hw) into the local cache:

   ```
   for id in <run ids>; do mkdir -p ~/.claude-teamB/routine-state/lab-deep-runs/$id; rsync -a lab:/srv/lab/runs/$id/{junit.xml,summary.json,run.json} ~/.claude-teamB/routine-state/lab-deep-runs/$id/; done
   ```

2. Save the `lab flakes` output to `/tmp/lab-deep-flakes.txt`.
3. Write the state first: `last_run` and the run ids under `runs`. When the bench did not run, set
   `runs.hw` to `[]` and `hw_skipped` to the reason; drop `hw_skipped` when it did. Leave `last_flakes` at the previous run's list until after the
   build; the report marks flakes missing from it as new.
4. Build:

   ```
   python3 ~/git/dotfiles/routines/lab-deep/build.py ~/git/dotfiles/routines/state/lab-deep.json \
     --runs-dir ~/.claude-teamB/routine-state/lab-deep-runs --flakes /tmp/lab-deep-flakes.txt \
     --ledger ~/.claude-teamB/routine-state/lab-deep-results.jsonl \
     --full ~/.claude-teamB/routine-reports/lab-deep.html --digest /tmp/lab-deep-digest.html
   ```

   The build appends one line per test per run to the ledger and skips runs already in it, so a rebuild
   is safe. The ledger is the only history source (trend, history dots, new/still red/fixed), since
   `lab gc` deletes old runs. It lives outside git on purpose.
5. Refresh the side panel: `t3_preview_list`, then `preview_navigate` the tab whose URL starts with
   `http://127.0.0.1:8765/lab-deep.html` to `http://127.0.0.1:8765/lab-deep.html?run=<YYYYMMDDHHMM>` with
   the run time; the query keeps the panel from showing the cached previous report. With no such tab,
   `preview_open` that URL. If the URL doesn't answer, run
   `launchctl kickstart -k gui/$(id -u)/local.routine-reports` and retry once; if it still fails, say so
   in the chat message.
6. `html_render` the digest with title "Lab deep run". It stays under 40,000 characters because
   `html_render` takes the page as a tool argument.
7. End with a short chat message. First line: passed, failed (known), skipped, the sha per group (tier 1,
   tier 2, hw). Then one line per new red (not still red, not known): the first line of its failure and
   your read on server or lab. A test that fails the same way on `dev` as on the previous day is a dev
   regression; a capture, fixture or lab-code error is the lab's. No fixes from this thread. Then a line
   for every `known_red` entry dropped this run. End with the footer "Reply `investigate <test>` to start
   a session on a red, `known <test>` to list it as a known red."
8. Set `last_flakes` to this run's flakes, then commit.

The full page: header with the runs per tier, the bench line and the total time; tiles for passed,
failed, skipped and pass rate with a 14-day trend; failures with new reds first, then still red, then
known, each with checkpoint, linked issues, the message, the traceback folded and a 7-day history; the
tests fixed since the previous run; a collapsible row per group with its tests; flakes; the slowest 10
tests; a filter box and an "Only failures" toggle. The digest is the same without tracebacks, groups and
slowest tests; a green day is just the header, the tiles and the footer.

## State

`{"last_run": "<date>", "runs": {"dev": [ids], "stable": [ids], "hw": [ids]}, "hw_skipped": "<reason,
only when the bench did not run>", "known_red": [{"test": "...", "since": "<date>", "note": "..."}],
"last_flakes": [...]}`. A `known_red` test is a node id or part of one; two tests join with " and ", and a
trailing note in parentheses is ignored when matching, and "on <set>" (such as "on spotify-a")
limits the entry to that set's group (`music_spotify`). Keep `known_red` current when Marvin
replies `known <test>`; drop an entry once the test passes two days in a row and say so in the chat message.
