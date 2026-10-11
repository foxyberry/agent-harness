---
name: handoff-consume-archives-before-delete
description: handoff-load retires the handoff it read through a separate `consume` step that archives a copy under the shared git directory, never commits, and removes nothing it cannot tie to the body `load` printed
type: decision
id: adr-20261011-001
chain: handoff-consume
status: active
supersedes: []
keywords: [handoff-load, consume, handoff-archive, .git/agent-harness, delete after restore, stale handoff, fingerprint, rename aside, staged copy, issue 138, uncommitted handoff]
commit: 1c4ae66
artifacts:
  - path: core/scripts/handoff.py
  - path: core/skills/handoff-load/SKILL.md
  - path: tests/test_handoff_consume.py
---

## Context

After a restore, `handoff-load` left the handoff document in place, so the next load read it
again and offered its already-handled done / remaining / next entries as restore material.
Issue #138 asked for the consumed document to be deleted after the report, the same way on the
Claude and Codex adapters, with nothing deleted when the restore failed or used session logs
only. The issue noted that a committed document is recoverable from Git history and an
uncommitted one is not, and left open when the resulting working-tree deletion gets committed.
The skill runs as a forked background context and had a report-and-stop rule (#17).

## Decision

`handoff-load` ends by running `consume --expect <fingerprint>`, which archives the current
branch's handoff to `<git common dir>/agent-harness/handoff-archive/` and then removes it,
without committing. It removes nothing unless the file's bytes still match the sha256 that
`load` printed.

## Alternatives

- **Delete and only report recoverability** — the behavior issue #138 described. Not taken: an
  uncommitted, staged-only or modified-after-commit handoff would be lost for good.
- **Commit the deletion as part of the restore** — raised in #138 as an open question
  ("Deleting does not by itself mean committing and pushing"). Not taken, so the user keeps
  control of commits.
- **Ask the user before deleting** — offered in this session as the alternative to automatic
  deletion. Not taken: the skill runs forked in the background and cannot ask mid-run, and the
  archive makes every state recoverable.

## Consequence

- The next load no longer offers a consumed handoff. Uncommitted handoffs stay recoverable from
  the archive; the output prints the archive path and the restore command.
- A committed handoff's deletion is left unstaged for the user to commit or restore.
- `consume` depends on the fingerprint from the `load` that ran just before it. It also refuses
  when the Git state is unreadable or a staged-only file's staged copy differs from disk
  (unstaging would drop that copy).
- The file is renamed aside before the check, and `save` writes via a temp file + rename, so a
  save racing a consume survives as a new file. Both guards came from Codex review on PR #173.
- The "report and stop" rule now has exactly one named exception.
- Archived copies accumulate under the git directory; no cleanup policy is decided.

## Evidence

- Issue #138 (problem, open questions on recoverability and committing).
- PR #173 and its Codex review comment: round 1 found the save race, round 2 the staged-copy
  loss, round 3 nothing.
- Commit 1c4ae66.
