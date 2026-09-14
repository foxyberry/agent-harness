---
name: fw-both
description: Resume work by comparing Claude and Codex session logs together. Use when work is spread across both tools; fw normally reads only the other tool.
context: fork
allowed-tools: Bash, Read, Grep, Glob
argument-hint: "Optional: --limit N sessions per tool, or a project path"
---

# Resuming across both tools (fw-both — forward work, both tools)

`fw` normally reads **one tool's** logs, defaulting to the other tool. This command reads **Claude and Codex logs together** to reconstruct work spread across both.

**Use it when** you have moved back and forth between tools and either tool's logs alone would miss part of the work.

**Live-session handling:** `--current codex` excludes the **current tool's live session only when its environment session ID matches a project log**. Without a positive match, it hides nothing. The other tool's latest log remains eligible; do not assume that tool has stopped running. Check the output for this invocation before treating it as prior work.

## Procedure

### 1. Read the root `AGENTS.md` first for project rules.

### 2. Load both tools' session logs and Git facts

```bash
python3 scripts/handoff.py fw --from both --current codex --project-dir "<absolute-path-to-user-project>"
```
> Paths under `scripts/` are relative to **the skill directory containing this SKILL.md**. Run the commands from that directory. Replace the `--project-dir` value with **the absolute path of the user project you are working on**. The skill may be in a plugin cache outside that repository; omitting this argument can select the wrong project.
- `--from both` includes Claude and Codex logs. `--current codex` enables the matching-based exclusion described above.
- `--limit N` increases the number of recent sessions summarized **per tool** (default: 1).
- Inspect:
  - **Chronological timeline** in each tool's summary: which tool calls followed each instruction and what happened last.
  - **Codex rollout summary** and **Claude JSONL summary**: latest inputs, responses, and tools from recent sessions.
  - **Current Git facts**: branch, commits relative to origin/main, changed files, and open PRs. Compare with the logs; Git takes precedence.

### 3. Combine the logs into completed work, remaining work, and the next action

Merge Claude and Codex activity **chronologically**, then compare it with current Git facts to establish actual progress. Do not repeat completed work.
- **Report and stop** (report-and-stop). **Propose** the next action. Run builds, tests, further validation, Git operations, or implementation only when the user explicitly requests them. Resuming restores and reports state; it does not itself authorize further work.

## Constraints

- **Current Git state takes precedence** over logs. Do not repeat work already committed, pushed, opened as a PR, or merged.
- `fw-both` requires **local logs on the same machine**. For another machine, use `handoff-save` and commit and push the file.
- Prefer `handoff-load` when a committed handoff is available; it is the canonical portable record. The `fw` commands are fallbacks when no handoff was saved.
- Before committing, follow the approval rules in `AGENTS.md` and rules against merging directly into main.
