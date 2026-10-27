---
name: self_review
description: Use to self-review the work done so far and get a second opinion from other models, or when the user says /self_review
---

# Self Review

Review the work we have done in this session, then get a second opinion from Opus 5.5 and GPT Sol 6.1.

## Steps

1. Write the full diff under review to `<scratchpad>/self_review/review.diff` (e.g. `git diff origin/dev...HEAD` plus uncommitted changes, from the worktree). Write a short `context.md` next to it: what we changed, why, and the files in scope.
2. Do your own review of the diff. Look for bugs, logic errors, missing edge cases, and deviations from the project standards.
3. In parallel, start both second opinions:
   - **Opus 5.5.** Agent tool, `subagent_type: general-purpose`, `model: opus`, `effort: high`. Give it the paths of `review.diff` and `context.md` and the worktree path. Ask for concrete findings only, each with `file:line`, a one-line problem and a one-line failure scenario.
   - **GPT Sol 6.1.** Run through the GitHub Copilot CLI (billed to Marvin's Copilot credits) with Bash `run_in_background: true`, `cwd` set to the worktree:

     ```bash
     copilot -p "$(cat <scratchpad>/self_review/prompt.md)" -s \
       --model gpt-6.1-sol --reasoning-effort high --no-ask-user \
       --add-dir <scratchpad>/self_review \
       --allow-tool='read' --deny-tool='write' --deny-tool='shell' \
       --deny-tool='url' --deny-tool='memory' \
       > <scratchpad>/self_review/gpt.md 2>&1
     ```

     `prompt.md` holds the same ask as the Opus prompt, with absolute paths to `review.diff` and `context.md`. Keep it read-only: never pass `--allow-all-tools`, `--allow-all` or `--yolo`. A run takes a few minutes and costs about 6.5 AI credits before the review itself.
4. Collect all findings. Merge overlapping points.

## Deciding

You own the end result. You decide which suggestions to accept or reject.

- For each accepted point, apply the fix.
- For each rejected point, say why in one line.
- Do not blindly follow the other models; only act on findings that are correct and matter.

## Output

Short summary grouped by: accepted (fixed), rejected (with reason), and anything still open for the user to decide. Note which model raised each point.
