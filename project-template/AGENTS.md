# AGENTS.md — <project name>

This file is the **single source of truth** for agent instructions.
Codex reads it directly, and for Claude Code `CLAUDE.md` pulls it in with `@import`.
(Do not maintain the two separately — rules always go here only.)

## Project overview

<One or two lines on what this repo is. Stack and main directories.>

## Working rules

- Never push directly to main — work on a branch and open a PR.
- <Commit approval rule, e.g. confirm with the user before committing>
- <Build/test command, e.g. ./gradlew test>

## PR description rules

- PR and issue titles and bodies are written **in English**. Korean is allowed only as an
  optional supplement in addition to the English text, never in place of it.
- Every PR title starts with a conventional type, e.g. `feat(scope): description`,
  `docs: description`. Do not prefix the title with a branch name or an emoji.
  GitHub's automatic revert titles are the exception.
- `feat`, `fix`, `refactor` and `perf` PRs explain what changed and how it actually works
  in English.
- The PR body must contain the `Implementation Summary (EN)` and `Implementation Logic (EN)`
  sections. A supplementary Korean section (for example `## Korean notes (optional)`) may be
  added after them; it is never a substitute for the English sections.
- The implementation logic describes the core execution order, branching, data flow, and
  failure and error handling in plain words. Listing changed file names or function names only
  does not count as an implementation description.
- `.github/workflows/pr-body-check.yml` checks that the two English sections exist and are not
  too short.

## Memory (agent-harness)

- Shared memory is **committed** under `.claude/memory/`. The list is `.claude/memory/INDEX.md`.
- The Claude plugin injects `INDEX.md` automatically at session start. Codex ships the same
  hooks, but its coverage is partial, so the fallback rule stands: if the index was not injected
  at session start, read `.claude/memory/INDEX.md` directly before starting work. When it was
  injected, do not read it again. The harness documents the Codex limits in
  <https://github.com/foxyberry/agent-harness/blob/main/docs/codex-hooks.md>.
- Hook data: `routes.json` (edited file or shell command → memory injection),
  `reflection-rules.json` (quality warning regexes), `reflect-skip.json` (skip rules for
  retrospective-output PRs).
  Adapt them to this project's language and rules — without them the hooks quietly no-op, and
  only the built-in TODO/FIXME check and the default retrospective skip rules remain.
- Governance: automatic retrospective drafts only accumulate in `_pending/` and are promoted
  **after human approval** through `/memory-update`. The automatic drafting job
  (`HARNESS_AUTO_REFLECT=1`) is supported on Claude; on Codex only merge detection and queueing
  run today. Secrets (keys, tokens, internal URLs) are forbidden in memory and handoffs.
- `.claude/.cache/` holds local hook and skill state and logs; it is not committed to Git.
- Memory holds only long-lived decisions, constraints and patterns. WIP, in-flight PRs and next
  actions are handed over only through `/handoff-save` at an actual switch point, and values you
  can recompute, such as line counts or test counts, are not stored.

## Handoff

- Before switching session, tool (Codex ↔ Claude), machine or person, run `/handoff-save` — it
  saves `.claude/handoff/<branch>.md` locally. Saving does not commit: commit and push that file
  under this project's commit approval rules, and never report a saved handoff as committed.
- To pick work back up, run `/handoff-load` — the committed handoff comes first, and the current
  git state always wins.
- If you do not know which session to resume, browse and search Claude and Codex logs read-only
  with `/history`, then pass the path you picked to `/fw --session`.
