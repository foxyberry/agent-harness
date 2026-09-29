---
name: reflect-skip-stays-project-config
description: Keep the retrospective skip list as per-project config with unchanged engine defaults, and adopt only the root .gitignore exception in this repository, rather than widening the engine defaults so an upgrade reaches everyone
type: decision
id: adr-20260929-002
chain: retrospective-skip
status: active
supersedes: []
keywords: [pr-merge-reflect, reflect-skip.json, ignore_paths, retrospective loop, engine defaults, adoption, gitignore]
commit: f4f1b32
artifacts:
  - path: .claude/memory/reflect-skip.json
  - path: core/hooks/pr-merge-reflect.py
---

## Context

A retrospective produces a PR, that PR merges, and the hook asks for a retrospective on it — a
loop a person has to break by hand each time (#130). The verdict requires **all** changed files to
match a skip path, so one incidental file breaks it: a memory-only PR that also touched the root
`.gitignore` was asked for its own retrospective. #134 added `ignore_paths` as a config key, but
the wide skip list and the `ignore_paths` values live in `project-template/`, which a plugin
upgrade does not copy into an existing project. So the engine shipped a capability no upgraded user
received.

## Decision

Leave the engine defaults alone and treat the skip list as project data. This repository adopts
`ignore_paths: [".gitignore"]` — the root file only. Rule documents, source code, shipped
templates and generated reference files stay in the verdict, and other projects adopt their own
config by hand using the guide in the PR.

## Alternatives

- **Widen the engine defaults** to include `CLAUDE.md`, `AGENTS.md`, `.claude/agents/**` and
  `.claude/skills/**`. Rejected: it reaches users on upgrade, but then a PR touching only
  skip-listed files gets no retrospective at all, and an `AGENTS.md`-only rule change is the
  realistic case — the loss would be silent. (Issue #130, option 1 in the reopening comment.)
- **Widen the defaults and record which PRs were skipped** so the loss is visible. Not taken: it
  answers the objection above by adding a second mechanism, and the distribution problem (#132)
  would still decide what each project actually runs. (Issue #130, option 3.)
- **Adopt a broad `ignore_paths` glob** rather than the root file. Rejected during review: nested
  globs also suppressed changes to the shipped templates, so a real template change would stop
  asking for a retrospective. The config was narrowed and regression cases were added.
  (PR #149 description and its review.)

## Consequence

The loop stops for this repository's memory-only PRs while every rule, code and template change
still asks for a retrospective. The accepted costs: other projects keep looping until someone
merges the config by hand, since `/template-check` reports the difference but never writes it, so
#130 stays open for that adoption; and the engine still decides nothing about incidental files, so
each project has to state its own exceptions. A separate defect surfaced in the same work — a
commit body that merely explains the `[skip reflect]` marker also skipped its PR — and was fixed
in #150 rather than folded into this decision.

## Evidence

- Issue [#130](https://github.com/foxyberry/agent-harness/issues/130), its reopening comment
  listing the three options, and the adoption comment; PR
  [#149](https://github.com/foxyberry/agent-harness/pull/149), commit `f4f1b32`.
- Follow-up: PR [#150](https://github.com/foxyberry/agent-harness/pull/150), commit `c2ae40f`.
- Tests: `tests/test_reflect_skip_adoption.py`, `tests/test_reflect_skip_scope.py`.
