---
name: squash-merge-consequences
description: This repo uses squash merge — ancestry-based checks (branch --merged) stop working, and a stacked PR needs a rebase once its base is merged
type: project
---

This repository **squash merges** PRs. A PR's commits land on main as one new commit, so **the
original branch tip never becomes an ancestor of main.** Two things follow.

**1. `git branch --merged` finds nothing**

Merged-ness has to be decided from the **PR head**, not from git ancestry
(`gh pr list --state all --json headRefName,state`). Branch deletion also needs `-D`, since `-d`
refuses.

**2. A stacked PR must be rebased once its base is merged**

If you only retarget a PR stacked on a base PR to main, **the base PR's old commits come along**
(the squash result has a different patch-id). Move just your own commits with
`git rebase --onto origin/main <old base>`, then change the base.

**Why:** measured 2026-08-07.
- A cleanup tool reported "0 merged local branches / 0 worktrees". In reality 22 of 23 local
  branches and all 3 worktrees were cleanup candidates. Only the sections that judged with
  `git branch --merged` were wrong; the remote section, which used the PR API, got it right —
  the cause was that the basis for the decision differed per section. (That tool moved to a
  personal skill on 2026-08-17. The squash-merge detection problem itself still stands.)
- PR #77 was stacked on #74, and once #74 was squash merged, simply changing the base would have
  mixed in #74's old commits. The user was the first to point out "shouldn't this be rebased?".

**How to apply:**
- Do not use `git branch --merged` to pick branch or worktree cleanup candidates. Decide with the
  PR API.
- For a stacked PR, right after the base is merged:
  `git rebase --onto origin/main <old base branch>` → force-push → `gh pr edit --base main`.
  Before switching, confirm with `git diff origin/main --name-only` that **only the intended
  files** are included.
- Check recoverability before deleting: a merged PR head's content is on main, and for a closed
  PR head GitHub keeps `refs/pull/<N>/head` permanently. **Only a local branch with no PR record
  at all is really gone** — get explicit confirmation for those.

Related: [[build-drift]]
