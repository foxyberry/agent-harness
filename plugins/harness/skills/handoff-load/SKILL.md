---
name: handoff-load
description: Resume work left by another session, tool, machine, or person. Prefer a committed handoff and compare it with current Git state.
context: fork
allowed-tools: Bash, Read, Grep, Glob
argument-hint: "Optional: a session UUID or transcript path for deeper recovery"
---

# Resuming from a handoff (handoff-load)

Recover work left by another session, tool (Codex or Claude), machine, or person.
**Prefer a committed handoff as the portable record**, supplemented by transcripts on the same machine.

## Procedure

### 1. Read the root `CLAUDE.md` first for project rules.

### 2. Load the handoff and current Git facts

```bash
agent-handoff load --deep
```

Inspect:
- **Target project**: first confirm that the selected repository is the intended one. The wrong repository can still produce valid-looking branches and sessions.
- **Handoff file**: summary, completed work, remaining work, next actions, and verification. **Verify that the file's current contents match the version in HEAD before treating it as committed.** An untracked file, a newly staged file, or changes to a previously committed file are not committed content. The current script's saved banner and load heading can incorrectly say "committed" (#133); neither is evidence. Check push status separately before claiming availability on another machine.
- **Current Git facts**: compare against the handoff for changes since it was written; Git takes precedence.
- **Deep-recovery hints**: available when this machine has local transcripts belonging to **this project**.
- **Claude JSONL and Codex rollout quick recovery**: summaries from both tools. Inspect timelines, latest prompts and responses, and task-output paths to recover interrupted work or background review results.

### 3. Optional deeper recovery — same machine and tool only

If `load --deep` is insufficient and a local transcript exists, use `/fw --from claude` or `/fw-both`
to read the `.jsonl` directly. To select a specific file, use
`agent-handoff load --deep --transcript <path/to/session.jsonl>`.
Skip this on another machine where the file is unavailable.

### 4. Summarize completed work, remaining work, and the next action, then **report and stop** (report-and-stop).

- Read and summarize the existing handoff rather than reconstructing everything from scratch. Treat it as the canonical portable record only after verifying its Git state; uncommitted content is a local draft.
- **Propose** the next action. Run builds, tests, further validation, Git operations (including commit/reset), or implementation only when the user explicitly requests them. Resuming restores and reports state; it does not itself authorize further work.

## Constraints

- **Current Git state takes precedence** over transcripts and handoffs. Do not repeat work already committed, pushed, or opened as a PR.
- Before committing, follow the approval rules in `CLAUDE.md` and rules against merging directly into main.
