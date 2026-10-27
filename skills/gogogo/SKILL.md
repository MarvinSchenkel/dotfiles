---
name: gogogo
description: "implement according to my standards"
---

please implement this enhancement/feature/bugfix - if bugfix (or maintenance), first verify if it is real, don’t blindly trust me or an issue reporter, always check facts.

Make sure to use the claude.md / copilot-instructions.md / agents.md file to be sure my preferred workflow is fresh in your memory.

If the solution (or fix for an issue) is not clear, first present a plan to me so we can work out the architecture first
only start coding immediately if the task is crystal clear for implementation.

After implementation, do a self-review using the self_review skill to ensure code quality and adherence to standards. When the self-review is complete and all critical / problem issues have been fixed, submit a PR, trigger a copilot review and babysit it until Copilot comes back green. For server PRs, also pass the lab gate below. Then mark the PR as 'Ready for review'.

## Lab gate (server PRs)
After the PR is pushed, run only the end-to-end lab areas the diff touches. Never run full tier 1 by default: it takes 20 to 30 min, and one area takes about 5 min.

1. Map every changed file to its area with the path-to-area guide in `lab/README.md`. Shared helpers can map to several areas. A `models/**` change means full tier 1.
2. If no file maps to an area (docs, tests only, frontend), skip the gate. If a player provider has no lab role, write "no lab coverage" in the PR.
3. Run the areas you found:

       /Users/marvin/git/music-assistant/lab/bin/lab run --ref pr/<n> --tier 1 --areas <area>[,<area>]

- Exit 0 is green. Anything else is red: treat it like a failing CI job. Investigate, fix, push, rerun the same areas. `pr/<n>` fetches the PR head, so every rerun tests the latest push.
- To read a failure, the CLI prints the run id. Check `/srv/lab/runs/<id>/summary.json` and `junit.xml` (via `ssh lab`), then `lab logs <id>` for the server log. Runbook: `lab/docs/runbook.md`, section "Reading a failed run".
- If the same test fails on `dev` too, it's a lab or dev problem, not this PR. Say so in the PR and don't block on it.
- If the lab is unreachable (`ssh lab true` fails, or labd doesn't answer), say so in the PR description and continue. Don't block on it.
- List the areas you ran and the result in the PR description.
- Auto approval also requires a green lab run when this gate applies.

## Auto approval
You are allowed to auto-approve in the server repository and merge your own PR if:
- The PR is deemed ‘ready to merge’ (self review and copilot have found 0 issues)
- The PR is S, M or L
- It does not touch any core code, meaning the diff is scoped to only providers/* and the related tests

The following important providers are EXCLUDED from auto approve behavior: 
- Sonos
- Airplay
- Spotify
- Sendspin
- Squeezelite

When you auto approve the PR:
- Use 'merge and bypass requirements' 