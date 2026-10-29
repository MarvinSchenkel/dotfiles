---
name: babysit
description: "Babysit the PR, monitor for CI status and Bot-MArley's review."
disable-model-invocation: false
---

Start off by requesting a review YOURSELF: comment `@Bot-MArley review` on the PR.

Keep monitoring the PR you submitted. Watch for CI status and Bot-MArley's review on the current head. Double check every Bot-MArley finding (its requested changes and inline threads) and verify if it is correct. Fix it if it makes sense to implement, dismiss otherwise. When in doubt, consult me with a popup question before continuing. Then reply to the thread and resolve it. After each push, comment `@Bot-MArley recheck` on the PR.

Keep checking until CI is green and Bot-MArley's latest review on the head is APPROVED with no open threads.
