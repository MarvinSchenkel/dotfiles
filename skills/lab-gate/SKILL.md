---
name: lab-gate
description: Use to run a Music Assistant server PR through the MA test lab, only for the areas its diff touches, or when the user says /lab-gate
---

# Lab gate

Run only the end-to-end lab areas a server PR touches and report the result. Input: the PR number. The caller decides when to run it, what to do with `models/**` and where the result goes.

## Steps

1. Map every changed file to its areas and `--providers` entries with "Path to area" in `/Users/marvin/git/music-assistant/lab/docs/pr-gate.md`. Read it every time, the map changes. Paths there are relative to `server/music_assistant/`. Take the union of the areas and the union of the provider entries.
2. If no file maps to an area or a provider entry (docs, tests only, frontend), skip: result `skipped`. A provider that `pr-gate.md` lists as "no lab coverage" also gives `skipped`, with that as the note.
3. A `models/**` change maps to `--all`, the full gate (20 to 30 min). Run it only when the caller allows it; otherwise the result is `nightly`.
4. Run the areas in the background and wait for them. One area takes about 5 min, and the lab takes 4 runs at once.

       /Users/marvin/git/music-assistant/lab/bin/lab run --ref pr/<n> --areas <area>[,<area>]

   Player provider rows (`--providers squeezelite` and so on) are their own command, not part of the `--areas` one: next to `--areas`, `--providers` only picks the players. Put the player domains of all such rows in one:

       /Users/marvin/git/music-assistant/lab/bin/lab run --ref pr/<n> --providers <domain>[,<domain>]

   For a device row or a music provider row, use the `--providers` command `pr-gate.md` gives for it. Never run `--deep`: the morning run covers that.

## Reading the result

- Exit 0 is green. A failing area is rerun once by the lab itself, so a red exit means a test failed twice.
- The CLI prints the run id. `lab summary <run id>` gives the failures per area. For more, check `/srv/lab/runs/<id>/summary.json` and `junit.xml` via `ssh lab`, and `lab logs <id>` for the server log. Runbook: `lab/docs/runbook.md`, section "Reading a failed run".
- If the same test fails on the latest morning run of `dev`, it's a lab or dev problem, not this PR: result `dev-red`, don't block on it.
- If the lab is unreachable (`ssh lab true` fails, or labd doesn't answer), result `unreachable`, don't block on it.
- `pr/<n>` fetches the PR head, so a rerun always tests the latest push.

## Output

The areas run, the result (`green`, `red`, `dev-red`, `unreachable`, `skipped` or `nightly`), the run id, and for red the failing tests with a one-line reason each.
