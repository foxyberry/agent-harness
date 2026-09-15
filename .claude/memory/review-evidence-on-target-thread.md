---
name: review-evidence-on-target-thread
description: Leave external review results on the target PR or issue thread, as the original text or a link, so they can be verified
type: feedback
---

When you report that an external review happened — Claude Code, Codex, a human reviewer — leave
the result as a **comment on the target PR or issue**. The author writing "review passed" in the
PR body is not a substitute for evidence of an independent review.

**Why:** on the public-release PR #72, the Claude Code review was done locally but never posted
as a PR comment, so the user could not confirm from the GitHub page that a review had happened.
From the follow-up PR #73 onward, posting the original review text and the cross-check result as
PR comments made the reviewer, the timing and the evidence immediately checkable.

**How to apply:** when a cross-review finishes, summarize the findings, the final judgment and
the verification you ran on the target thread. If the original review lives on another thread,
such as a related issue, link that comment directly from the target PR. Do not describe a state
where the only artifact is local CLI output as "PR review complete".
