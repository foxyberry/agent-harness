---
name: template-check
description: Compare the project's .claude/memory/ against the template reference bundled with the installed harness plugin, read-only. Use after a plugin update, or when a harness feature expects a project file that may never have been copied.
allowed-tools: Bash, Read
---

# template-check

The opinion pack in `project-template/` is copied into a project once, so files added to it later never reach a project that adopted it earlier. The installed plugin ships a read-only copy of the pack's `.claude/memory/` as a comparison reference, and this command lists how the project differs from it. The rest of `project-template/` (`AGENTS.md`, `CLAUDE.md`, `.github/`) is not shipped and not compared.

{{PROJECT_ROOT_NOTE}}

## Usage

```bash
{{TEMPLATE_CHECK}} --project-dir "{{PROJECT_ROOT}}"
{{TEMPLATE_CHECK}} --project-dir "{{PROJECT_ROOT}}" --json
```
{{PATH_NOTE}}

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
