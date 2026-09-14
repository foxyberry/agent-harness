---
name: handoff-save
description: Save a portable handoff file for committing before ending a session or passing work to another tool, machine, or person.
context: fork
allowed-tools: Bash, Read, Grep
argument-hint: "Optional: a one-line summary, such as client consolidation 80% complete"
---

# Saving a handoff (handoff-save)

Before ending a session or passing work to **another tool (Codex or Claude), machine, or person**, save the current state in a handoff file intended for Git.

Transcripts (`.jsonl`) are local and tool-specific. A handoff becomes available to other machines, people, and agents through clone/pull **after it is committed and pushed**.

## Procedure

### 1. Summarize the work in four parts

- **Summary**: one or two lines explaining the task.
- **Completed work**: finished items as bullets.
- **Remaining work / next actions**: concrete bullets the recipient can act on.
- **Verification**: test, build, and review results.

### 2. Run the script with Markdown and actual newlines

```bash
{{HANDOFF}} save {{PROJECT_DIR_ARG}}\
  --agent {{AGENT}} \
  --summary "One- or two-line summary" \
  --done "- Completed item 1
- Completed item 2" \
  --next "- Next action 1
- Next action 2" \
  --verify "Verification status"
```
{{PATH_NOTE}}
The script **collects Git facts automatically**: branch, commits relative to origin/main, changed files, and open PRs.
It creates or updates `.claude/handoff/<branch-name>.md`, with one file per branch (slashes in the branch name become hyphens, and spaces become underscores).

### 3. Explain the commit and push step

Saving creates a local file; the script **does not commit or push it**. Commit and push it to pass it to another machine.
Follow the commit approval rules in `{{RULES_FILE}}`; obtain user confirmation before proceeding.
The current script writes a banner claiming the file is committed even when it is not (#133). Verify the file's current contents against Git and report its actual state; do not repeat that claim based on the banner alone.

## Constraints

- Do not leave narrative sections empty; an empty handoff is unusable.
- Write `--next` so the recipient knows what to do without first reading `git diff`.
- Do not include sensitive information such as keys, tokens, or private URLs; this file is intended for committing.
