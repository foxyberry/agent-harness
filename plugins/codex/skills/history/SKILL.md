---
name: history
description: List and search local Claude and Codex session logs chronologically, and print an fw command for resuming a selected log.
context: fork
allowed-tools: Bash, Read
argument-hint: "Optional: --from / --limit / --since / --grep / --no-content"
---

# history

`history` is a **read-only discovery step**, not recovery itself. Find the session to resume, then use the printed `fw --session` command to recover its context.

## Usage

```bash
python3 scripts/handoff.py history --project-dir "<absolute-path-to-user-project>" --from both --limit 20 --since 30d
python3 scripts/handoff.py history --project-dir "<absolute-path-to-user-project>" --grep "useStudyProgress" --since 7d
python3 scripts/handoff.py history --project-dir "<absolute-path-to-user-project>" --no-content
```
> Paths under `scripts/` are relative to **the skill directory containing this SKILL.md**. Run the commands from that directory. Replace the `--project-dir` value with **the absolute path of the user project you are working on**. The skill may be in a plugin cache outside that repository; omitting this argument can select the wrong project.

Output includes:
- Modification time and tool (Claude or Codex).
- Full log path.
- Project-matching method.
- Latest user-input snippet.
- A copyable `fw --session <path>` command for the selected log.

## Options and limits

- `--from claude|codex|both` (default: both).
- `--limit N` (default: 20).
- `--since 30m|12h|7d|2w` (default: 30d).
- `--grep <keyword>` searches complete JSONL files case-insensitively, within at most the 200 newest candidate files in the requested time window.
- `--no-content` lists paths and metadata without displaying prompts in the terminal.
- `--json` provides output for automation.

Log formats may change between tool versions, so parsing is best effort. An unparseable snippet is left empty without failing the whole listing. Claude's project-directory keys and Codex rollout `cwd` values identify the project; false matches and omissions remain possible.

A resumed Codex rollout may have a recent modification time inside an old start-date directory. Discovery therefore checks modification times across the full session tree before applying `--since`, rather than filtering by directory date.

`history` only lists, searches, and prints paths. It neither recovers sessions automatically nor modifies logs.
