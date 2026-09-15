---
name: close-the-issue-close-the-doc
description: If a doc says "known bug / unverified / limitation", fix the doc when you close that issue — otherwise something already fixed stays documented as broken
type: project
---

The moment a doc says **"known bug", "unverified" or "known limitation"**, that sentence is
paired with an issue. When you close the issue, or merge the PR that removes the limitation,
**fix the doc in the same PR.** If the person who fixed it does not fix the doc, nobody will —
and the next person to open that doc reads a fixed thing as a bug.

**Why:** a full documentation sweep on 2026-08-31 turned up three cases.

- `docs/guide.md` — "known bug #81: `/feedback-review` does not look at `_pending` or past
  sessions". #81 was closed by #119 on 08-19. For 12 days a working feature was documented as
  broken.
- `docs/self-improvement-hooks.md` — "the draft parser can truncate on nested code fences".
  `reflect.py` already uses a variable-length fence, `^(` + backtick`{3,})`. It was already fixed.
- `docs/self-improvement-hooks.md` — "live-fire unverified, moved to issue #3". #3 was closed,
  and **the README stated the same fact as "verified"**. Two documents claimed the opposite.

The last one is the worst. It is not that one is out of date — **which conclusion you reach
depends on which document you read.** The reader has no idea the repository contradicts itself.

**How to apply:**

- When you put an issue number in a doc, treat **that doc as a subscriber to that issue**. Put
  "docs that mention this number" on the checklist of the PR that closes it:
  `grep -rn "#<number>" README*.md docs/ AGENTS.md`
- A PR that **removes** a limitation or an unverified caveat does not end with the code. Deleting
  that sentence, or changing it to "fixed", is part of that PR.
- When you delete it, **do not just delete it — say what changed.** "#81 is fixed — `_pending` is
  now always included, and past sessions only when a human selects them" is better than a blank
  space. The next person does not have to ask the same question again.
- Conversely, **do not delete a limitation that is still true.** In the same sweep, the item
  "the reflection job treats a successful spawn as seen" was left in place after checking the
  code. Deleting true statements while tidying up is also a loss.

Related: [[review-evidence-on-target-thread]]
