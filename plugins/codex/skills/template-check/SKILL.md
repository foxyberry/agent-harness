---
name: template-check
description: Compare the project's .claude/memory/ against the template reference bundled with the installed harness plugin, read-only. Use after a plugin update, or when a harness feature expects a project file that may never have been copied.
allowed-tools: Bash, Read
---

# template-check

The opinion pack in `project-template/` is copied into a project once, so files added to it later never reach a project that adopted it earlier. The installed plugin ships a read-only copy of the pack's `.claude/memory/` as a comparison reference, and this command lists how the project differs from it. The rest of `project-template/` (`AGENTS.md`, `CLAUDE.md`, `.github/`) is not shipped and not compared.

> **Project root.** Before anything else, resolve `<absolute-path-to-user-project>` to the absolute path of the user project this request is about, from the user request or the session working directory (for example `/home/me/src/my-app`). Resolve it **before** any `cd` into the skill directory, and retain that same value for every **project-file** read, write and delete below, and for the `--project-dir` argument in the command examples. It is the root for project files only: the Claude personal-memory directory and the bundled `scripts/` have their own separate roots. Never derive it from the plugin cache path, and do not substitute a sibling worktree or primary checkout that merely shares the same Git remote. Do not rely on a shell variable to carry it across tool calls; write the absolute path literally in each command and path.

## Usage

```bash
python3 scripts/template_check.py --project-dir "<absolute-path-to-user-project>"
python3 scripts/template_check.py --project-dir "<absolute-path-to-user-project>" --json
```
> Paths under `scripts/` are relative to **the skill directory containing this SKILL.md**. Run the commands from that directory. Replace the `--project-dir` value with **the absolute path of the user project you are working on**. The skill may be in a plugin cache outside that repository; omitting this argument can select the wrong project.

`--project-dir` is required and must be an absolute path to a directory; it is never guessed from the working directory. If the user asks for `--json` or `--verbose` (which also lists identical files), add it to the command.

## Reading the result

Each reference file gets one status:

- **missing** — the project has no file at that path. Some reference files are optional examples, so an absence can be intentional.
- **differs** — the file exists with different content. This can be a deliberate customization or an older copy; no record of the copied template version exists, so the check cannot tell which. Do not describe such a file as outdated.
- **identical** — same content (CRLF and LF line endings are treated as equal).
- **skipped** — not compared, with a reason (for example a link that resolves outside the project). Any skipped file means the comparison is incomplete, so do not report the project as matching.

The report prints paths, statuses, and the location of each reference copy, never project file content.

## What to report

Summarize the result for the user and give a per-file suggestion: for a missing file, what the reference copy is for and whether this project appears to need it; for a differing file, that the user can compare it with the reference copy if they want to review it. Read reference copies when that helps explain them.

This command is read-only: it does not copy, merge, or edit anything, and neither does this skill. If the user then asks to adopt a file, treat that as a separate request.
