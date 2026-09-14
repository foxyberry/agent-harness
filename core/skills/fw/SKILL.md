---
name: fw
description: Resume work from the other tool (Codex or Claude) by recovering its session logs, even without handoff-save. Use when switching tools after reaching a plan or quota limit.
context: fork
allowed-tools: Bash, Read, Grep, Glob
argument-hint: "Optional: --from claude|codex (defaults to the other tool), or a session log path"
---

# Resuming across tools (fw — forward work)

Use this command to **switch tools and resume work after reaching a plan or quota limit**.
For example, work in Codex, then open Claude to recover that work, or vice versa.

**How this differs from handoff:**
- **handoff-save/load** uses an explicitly saved handoff file. Once committed and pushed, it is the **canonical portable handoff**, preferred across machines and tools.
- **fw** is a fallback that **recovers session logs without a prior save** (Claude `.jsonl` or Codex rollout files). It works only on the same machine.
- Prefer `handoff-load` when a committed handoff is available. **Current Git state always takes precedence over logs.**

## Procedure

### 1. Read the root `{{RULES_FILE}}` first for project rules.

### 2. Detect session logs and load Git facts

```bash
{{HANDOFF}} fw --from {{FW_FROM_DEFAULT}} --current {{AGENT}} {{PROJECT_DIR_ARG}}
```
{{PATH_NOTE}}
- `--from {{FW_FROM_DEFAULT}}` defaults to **the other tool**, for switching tools.
- `--current {{AGENT}}` excludes the current tool's live session **only when its environment session ID matches a project log**. Without a positive match, it hides nothing; inspect the output to avoid treating this invocation as previous work.
- Inspect:
  - **Chronological timeline**: which tool calls followed each instruction; use it to identify the last action.
  - **Session summary**: latest user input, assistant response, tools, and task notifications.
  - **Current Git facts**: branch, commits relative to origin/main, changed files, and open PRs. Compare these with the logs; Git takes precedence.

**If a session ended in the same tool** (reboot, `/clear`, or context exhaustion), read **this tool's** logs:

```bash
{{HANDOFF}} fw --from {{AGENT}} --current {{AGENT}} {{PROJECT_DIR_ARG}}
```

The identified live session is excluded so earlier work can be selected. Use `/fw-both` if work spans both tools.
To select a particular log, add `--session <log-path>`; `/history` can find that path.

### 3. Summarize completed work, remaining work, and the next action

Compare the logs (what was being done) with current Git facts (what actually exists).
- Even if a log says a PR was created, **verify** push and merge status with Git/gh to avoid repeating completed work.
- **Report and stop** (report-and-stop). **Propose** the next action. Run builds, tests, further validation, Git operations, or implementation only when the user explicitly requests them. Resuming restores and reports state; it does not itself authorize further work.

## Constraints

- **Current Git state takes precedence** over logs and handoffs. Do not repeat work already committed, pushed, opened as a PR, or merged.
- `fw` requires **local logs on the same machine**. For another machine, use `handoff-save` and commit and push the file.
- Before committing, follow the approval rules in `{{RULES_FILE}}` and rules against merging directly into main.
