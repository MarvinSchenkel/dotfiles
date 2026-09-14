---
name: gogogo
description: "implement according to my standards"
---

please implement this enhancement/feature/bugfix - if bugfix (or maintenance), first verify if it is real, don’t blindly trust me or an issue reporter, always check facts

use subsessions where/if possible to execute the work and pick an appropriate model for each work session.
prefer opus 4.8 over opus 5.0
review the work of each session here and communicate in this session with me
if the solution (or fix for an issue) is not clear, first present a plan to me so we can work out the architecture first
only start coding immediately if the task is crystal clear for implementation.

please follow our code guidelines and styling in mind as you see in the existing code and the claude.md
also keep our preference in mind for multi line docstrings where the first line starts on the next line
inline comments in the code are there to explain code parts that need explaining, keep that in mind yourself when writing code but also repect existing comments from authors - they apparently had a reason to write the comment, dont remove them unless needed

docstrings should be clear for a consumer of the function/method (and not explain the internal working) - comments are there to clarify the behavior of the code that is not immediately clear from a first look. Also when refactoring/fixing something, no need to refer to what was there previously or what you fixed (that is more for a PR description). Comments and docstrings should be there for the CURRENT code, not the previous code. 
Keep comments/dosstrings focused, short and to the point. Docstrings of private methods should be oneliners without param and return type defintion

private methods should be at the bottom of the file, public at the top

Check yourself on every step.
Ask questions if there's littlest ambiguity.
Don't accept "good enough" solution, make it the best one, robust, complete, optimized, effective and architecturally perfect.
Also make minimal changes to the code upon refactoring, be short and specific, unless it is needed to fulfill the above requirements and/or we have agreed this is the goal. But flagging a need for wider refactoring is always good if that ensures better long-term code maintenance and readability. Propose to do so if it makes sense in this round, otherwise propose as follow-up

Use SOLID principles where it's reasonable.
Use KISS principle, don't over-complicate solutions. They should be laconic and sharp.

Always be REALISTIC - don’t attempt to fix a potential issue under a certain edge case situation that may never happen under normal situations.
Especially not if it’s hard to proof that this situation will even arrise.
If such a case may happen, we will get a user issue report and we can act on that.

If you want to ask me a question, don’t bury the question(s) or proposal in a bunch of text but open a dialog with that question (or whatever that is called in your tooling) and we go over them one by one

-------------------------------

once/if the direction of the implementation is clear and 
push this to a branch and create a PR 

- act on my behalf/username
commit on my behalf (not yours)
- Create a short PR description, which clearly explains what change we made and why it was needed
- No need to credit claude code or copilot 
- keep it short, to the point with a problem/feature description and a bullet list of changes
Use user friendly (short) PR title and description, try to avoid jargon where possible as the PR’s will be referenced in user-facing release notes
A short (bulleted) list of things changed if often fine enough instead of going all-in on details
- no test plan and such that bloats the description
if there is a PR template on the repo, dont overwrite it, but respect it
- please follow our code guidelines and styling in mind as you see in the existing code and the claude.md
use a user friendly PR title - we use labels (in the PR template) to categorize
always open the PR as draft first and trigger copilot review (you need to manualy trigger it)
Only open a draft PR with my explicit permission
always request a review from another agent/subsession on the PR to catch things you didnt 
mark the PR as ready once everything is settled. If you still have open questions with me or are working on something, keep it draft
use bugfix label/category if this fixes a REAL reported bug, use enhancement if this adds a small new feature/capability to an existing provider/feature. Only use the new-feature category/label if this is actually a brand new user-facing feature. Same for the new-provider category/lavel. Only tick that if this is a complete new provider. If not really user facing, use maintenance label. When in doubt, ask me.
We use the maintenance label on the PR and pr description if this is not really fixing a user reported bug or a (directly) user visible enhancement 

watch the CI and copilot auto review after the PR was created for any errors and autofix
please have a look at copilot's review comments, 
fix the ones that need fixing or comment why they dont - in case of doubt, always ask me first what to do
always recheck what copilot flags as its not always right or missing some context
respond in my behalf with comments but keep them short, to the point and in my human style of communication
resolve the conversations that are settled and done (or outdated)
if an existing test fails, we should carefully review if we did not cause a regression instead of blindly adjusting existing tests to make it fit the new reality.

Make sure that the branch is up to date and rebase it when needed. If a merge conflicts that arises, carefully review why it happened and if another PR didnt test the same code.

Flag any follow-up, cleanup or related issues where possible and where needed, spin up chips for those follow-up tasks that are not strictly needed to complete this task but will improve the overall implementation. Spin up the chips only after the whole implementation has landed (PR merged).