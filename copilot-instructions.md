# General engineering guidelines I want you to follow:
- also keep our preference in mind for multi line docstrings where the first line starts on the next line
- inline comments in the code are there to explain code parts that need explaining, keep that in mind yourself when writing code but also repect existing comments from authors - they apparently had a reason to write the comment, dont remove them unless needed
- docstrings should be clear for a consumer of the function/method (and not explain the internal working) 
- Only use comments when the code is not obvious and needs explanation
- When writing comments, prefer concise one or twoliners over long paragraphs.
- Also when refactoring/fixing something, no need to refer to what was there previously or what you fixed (that is more for a PR description). 
- Comments and docstrings should be there for the CURRENT code, not the previous code. 
- Private methods should be at the bottom of the file, public at the top
- Docstrings of private methods should be oneliners, no param definitions.

# Behaviour guidelines:
- Check yourself on every step.
- Ask questions if there's littlest ambiguity.
- If the solution (or fix for an issue) is not clear, first present a plan to me so we can work out the architecture first
- Only accept "the best" solution, make it the best one, most robust, complete, optimized, effective and architecturally perfect.
- Also make minimal changes to the code upon refactoring, be short and specific, unless it is needed to fulfill the above requirements and/or we have agreed this is the goal.
- Use SOLID principles where it's reasonable.
- Use KISS principle, don't over-complicate solutions. They should be laconic and sharp.
- Only post to Github with my explicit permission
- Only change a test with my permission. If a test fails, it means there is a regression. Consult me first.
- Only run the tests that are relevant to the code you changed. CI will run the full suite.
- Use subsessions where/if possible to execute the work and pick an appropriate model for each work session, review the work of each session here and communicate in this session with me
- For all coding tasks use your judgement to decide an appropriate lower power model and run that in a subagent
- Only start coding immediately if the task is crystal clear for implementation.
- If an existing test fails, we should carefully review if we did not cause a regression instead of blindly adjusting existing tests to make it fit the new reality.
- Flag any follow-up, cleanup or related issues where possible and where needed, spin up chips for those follow-up tasks that are not strictly needed to complete this task but will improve the overall implementation. Spin up the chips only after the whole implementation has landed (PR merged).

# My preferred PR workflow:
- Always work in a worktree to prevent clashing with other agents
- Act on my behalf/username
- Commit on my behalf (not yours)
- Create a short PR description, which clearly explains what change we made and why it was needed
- No need to credit claude code / Copilot / Copilot app
- keep it short, to the point with a problem/feature description and a bullet list of changes
- No test plan and such that bloats the description
- if there is a PR template on the repo, dont overwrite it, but respect it
- Use a user friendly PR title - we use labels (in the PR template) to categorize
- Only create PRs when I ask you to
- When I ask you to create a PR, always publish the PR as draft first, I will set it to ‘ready for review’ myself
- Watch the CI and copilot auto review after the PR was created for any errors and autofix
- Please have a look at copilot's review comments, 
- Fix the ones that need fixing or comment why they dont - in case of doubt, always ask me first what to do
- Always recheck what copilot flags as its not always right or missing some context
- Respond in my behalf with comments but keep them short, to the point and in my human style of communication
- Resolve the conversations that are settled and done (or outdated)
- Make sure that the branch is up to date and rebase it when needed. If a merge conflicts that arises, carefully review why it happened and if another PR didnt test the same code.