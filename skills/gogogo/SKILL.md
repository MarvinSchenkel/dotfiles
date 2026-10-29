---
name: gogogo
description: "implement according to my standards"
---

please implement this enhancement/feature/bugfix - if bugfix (or maintenance), first verify if it is real, don’t blindly trust me or an issue reporter, always check facts.

Make sure to use the claude.md / copilot-instructions.md / agents.md file to be sure my preferred workflow is fresh in your memory.

If the solution (or fix for an issue) is not clear, first present a plan to me so we can work out the architecture first
only start coding immediately if the task is crystal clear for implementation.

After implementation, do a self-review using the self_review skill to ensure code quality and adherence to standards. When the self-review is complete and all critical / problem issues have been fixed, submit a PR, comment `@Bot-MArley review` on it and babysit it until Bot-MArley approves the current head. For server PRs, also pass the lab gate below. Then mark the PR as 'Ready for review'.

## Lab gate (server PRs)
After the PR is pushed, run the lab-gate skill on it. A `models/**` change may run the full tier 1 gate.

- Red is a failing CI job: investigate, fix, push, rerun the same areas.
- List the areas you ran and the result in the PR description. Write "no lab coverage" when the skill skipped a provider for that reason, and say so when the result is `dev-red` or `unreachable`.
- Auto approval also requires a green lab run when this gate applies.

## Auto approval
You are allowed to auto-approve in the server repository and merge your own PR if:
- The PR is deemed ‘ready to merge’ (self review found 0 issues and Bot-MArley APPROVED the current head)
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

When the linked PR is merged, first make sure to spin up any follow-up chips (when applicable), then settle the thread in T3 code.