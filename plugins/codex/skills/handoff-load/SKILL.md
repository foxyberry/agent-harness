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

### 1. Read the root `AGENTS.md` first for project rules.

### 2. Load the handoff and current Git facts

```bash
python3 scripts/handoff.py load --deep --project-dir "<absolute-path-to-user-project>"
```
> Paths under `scripts/` are relative to **the skill directory containing this SKILL.md**. Run the commands from that directory. Replace the `--project-dir` value with **the absolute path of the user project you are working on**. The skill may be in a plugin cache outside that repository; omitting this argument can select the wrong project.
Inspect:
- **Target project**: first confirm that the selected repository is the intended one. The wrong repository can still produce valid-looking branches and sessions.
- **Handoff file**: summary, completed work, remaining work, next actions, and verification — the primary portable record. Read the **Git-state line** printed just above the body first; it, not any sentence inside the body, is the file's real state. It reports one of: not committed (the handoff exists only on this machine, whether or not it is staged); committed but since modified (the printed body is working-tree content that is not in HEAD); committed and identical to HEAD; or not determinable, meaning Git could not be queried and nothing should be assumed. Even a committed result is a **local commit only** — push status is not checked, so confirm it separately before claiming the handoff is available elsewhere. The comparison is byte-for-byte against the HEAD blob, so line-ending or filter differences can report "modified"; it judges this one file's content, not the state of the rest of the index.
- **Current Git facts**: compare against the handoff for changes since it was written; Git takes precedence.
- **Deep-recovery hints**: available when this machine has local transcripts belonging to **this project**.
- **Claude JSONL and Codex rollout quick recovery**: summaries from both tools. Inspect timelines, latest prompts and responses, and task-output paths to recover interrupted work or background review results.

### 3. Optional deeper recovery — same machine and tool only

If `load --deep` is insufficient and a local transcript exists, use `/fw --from codex` or `/fw-both`
to read the `.jsonl` directly. To select a specific file, use
`python3 scripts/handoff.py load --deep --project-dir "<absolute-path-to-user-project>" --transcript <path/to/session.jsonl>`.
Skip this on another machine where the file is unavailable.

### 4. Summarize completed work, remaining work, and the next action, then **report and stop** (report-and-stop).

- Read and summarize the existing handoff rather than reconstructing everything from scratch. Do not assume it is committed: if the Git-state line reports uncommitted, modified, or unverifiable, say so in the report — the content may not be shared yet, or may diverge from HEAD.
- **Propose** the next action. Run builds, tests, further validation, Git operations (including commit/reset), or implementation only when the user explicitly requests them. Resuming restores and reports state; it does not itself authorize further work.

## Constraints

- **Current Git state takes precedence** over transcripts and handoffs. Do not repeat work already committed, pushed, or opened as a PR.
- Before committing, follow the approval rules in `AGENTS.md` and rules against merging directly into main.
