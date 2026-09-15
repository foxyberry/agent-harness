---
name: cache-must-outlive-target
description: Where to store a cache, alias or index — never inside something that disappears, such as a worktree, a session or a temp folder. Worktree state goes under the shared .git directory
type: project
---

**Use this rule when deciding where to store a cache, an alias or an index.**

Before picking a location, ask one question — **"when the thing I am recording disappears, does
this record disappear with it?"** If so, the location is wrong.

| What is recorded | Where it must not go | Where it goes |
|---|---|---|
| worktree information | inside the worktree (`<worktree>/.claude/.cache/`) | under `git rev-parse --git-common-dir` |
| session / transcript information | that session's temp folder | the project or the home directory |
| state about a temp folder | inside that temp folder | somewhere that outlives it |

Under `git rev-parse --git-common-dir` (`<repo>/.git/agent-harness/`) is a good default for
worktree-related state — it is the only location that is **shared by every worktree, survives
worktree deletion, and stays out of commits** at the same time.

**Why:** caught as a P1 by the Codex cross-review on PR #80, 2026-08-07.

The alias cache existed so that after a worktree was removed you could still trace "which repo
was this path?", but it was stored at `project_dir/.claude/.cache/`. When `project_dir` is
itself a linked worktree, the cache is created **inside that worktree** — delete the worktree
and the cache goes with it. On top of that the main checkout reads a different cache, so the two
never see each other. **The record made for tracing back was missing at exactly the moment it
had to trace back.** Moving it inside `.git` fixed it.

The signature of this bug is that it looks fine on its own — test from the main checkout and it
passes. It only shows up if you separately test the path where a worktree is passed as
`project_dir`.

**How to apply:**
- When writing code that uses a cache path, assume `project_dir` **may be a worktree**.
- If a target was never observed, **give up instead of guessing**. Inferring from a name or the
  shape of a path produces false positives, and a wrong recovery is worse than no recovery.
- Write the test as **"record from a worktree → delete that worktree → look it up from the main
  checkout"**, not "record from the main checkout → look it up from the main checkout". The
  latter cannot catch this bug.

Related: [[committed-artifact-env-leak]], [[engine-data-separation]]
