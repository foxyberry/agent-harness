---
name: template-check-compares-without-copying
description: Ship template drift detection as a read-only comparison the user invokes with an explicit project path, instead of a SessionStart alert or a sync command that fills in missing files
type: decision
id: adr-20260929-001
chain: template-drift
status: active
supersedes: []
keywords: [template-check, project-template, drift, .claude/memory, PACK_VERSION, read-only, adoption, opinion pack]
commit: cb3e635
artifacts:
  - path: core/skills/template-check/SKILL.md
  - path: core/scripts/template_check.py
---

## Context

The plugin updates itself, but `project-template/` is copied into a project once by hand, so a
project that adopted the pack early silently ages. The reported case: the `memory-update` skill
pointed at `.claude/memory/decisions/README.md` as the canonical ADR schema, and an adopted
project did not have that file, which blocked promotion there. `reflect.py` also reads
`decisions/` while excluding `README.md` and the example file — it assumes they exist (#132).

## Decision

`/template-check` compares the `.claude/memory/` of an explicitly named project against a
read-only template reference bundled in both adapters, and reports each file as missing,
different, identical or skipped. It never writes to the project, and it compares only
`.claude/memory/` — project rules, GitHub workflows and existing ADRs are out of scope.

## Alternatives

- **Detect drift at SessionStart and warn, using a `PACK_VERSION` marker in the pack.** This was
  the reporter's first-priority proposal. Not taken: a file that differs is often an intentional
  customization, so a version-marker comparison would warn on every customized project at every
  session start. (Issue #132, proposal 1, and the design comment on #132 listing "no SessionStart
  alert" as a limit.)
- **A `build.sh` sync subcommand that fills in missing files.** Proposal 2 in the same issue. Not
  taken: the same false-positive problem becomes a write. The design review explicitly removed the
  automatic-copy guidance from the implementation. (Issue #132, proposal 2, and the design comment:
  "No project files changed. No automatic copying, ADR migration, or plugin cache changes.")
- **Migrate the pre-pack ADR files in an adopted project.** Proposal 4. Not taken in this stage and
  left as separate work, since rewriting 12 existing records is not reversible by re-running a
  check. (Issue #132, proposal 4.)

## Consequence

A project can see what it lacks without risking its own edits, and the ADR schema no longer
depends on a template file, because `memory-update` now carries the schema inline. The accepted
costs: adoption stays manual, so a project can read the report and do nothing; nothing warns
automatically, so someone has to run the command; and this does not close #132, whose drift
detection and upgrade path remain open. The check also made the `reflect-skip.json` adoption gap in
#130 visible, which is what the next decision in this loop acts on.

## Evidence

- Issue [#132](https://github.com/foxyberry/agent-harness/issues/132) with its design and
  completion comments, PR [#146](https://github.com/foxyberry/agent-harness/pull/146).
- `/template-check` ships in both adapters; the bundled reference is a copy of
  `project-template/.claude/memory/`.
