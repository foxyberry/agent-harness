---
name: alternatives-must-be-sourced-not-invented
description: An ADR's Alternatives section must come from an option rejected in a real source with that source cited in Evidence; a candidate with no stated rejection fails the gate instead of being filled in
type: decision
id: adr-20260922-003
chain: decision-capture
status: active
supersedes: []
keywords: [ADR, Alternatives, gate, invented rationale, mine.py, Evidence, sourcing, supersedes chain]
commit: c59a226
artifacts:
  - path: core/skills/memory-update/SKILL.md
---

## Context

The §1.6 gate requires an `## Alternatives` section before a candidate can be promoted. Run over
the last 10 commits, `mine.py` produced this repository's first draft with two rejected
alternatives — "always fetch full messages regardless of truncation" and "treat a failed REST fetch
as an error" — neither of which appears in commit `c5f2ab7`, the draft's only cited evidence. The
option actually rejected lived in the PR #152 body, which `mine.py` does not read. The model filled
the section because the gate demanded it. Promoting that draft unchanged would have recorded a
decision history that never happened, with later `supersedes` chains built on top of it; PR #154
had to rewrite the section against the real sources before the first ADR could be promoted.

## Decision

`## Alternatives` must come from an option rejected in a real source — this session, the PR or
issue text, or a code comment — and `## Evidence` must name where each one came from. If no
alternative was rejected anywhere, the candidate fails the gate: it becomes ordinary memory or is
discarded. The section is never filled to make the gate pass.

## Alternatives

- **Keep the gate as it is and accept model-filled sections.** Rejected: an invented section is
  worse than an empty one, because it asserts a decision history that never happened and
  `supersedes` chains are then built on it. (Diagnosis comment on issue #153.)
- **Label mined alternatives as a hypothesis rather than a record.** This is what the #153 comment
  proposed. Not taken: a hypothesis stored in the same field as a record is indistinguishable once
  the ADR is read later, so the rule requires sourcing and fails the gate instead. (Issue #153
  comment; PR #155 description.)

## Consequence

Fewer candidates become ADRs — one with no stated rejection now lands in ordinary memory — in
exchange for no invented history in the decision graph. The accepted cost falls on backward
mining: a draft mined from a commit-only slice will usually fail this rule, so `mine.py` adds
little until it reads PR and issue bodies.

## Evidence

- Issue [#153](https://github.com/foxyberry/agent-harness/issues/153) diagnosis comment (the two
  unsourced alternatives, measured), PR [#154](https://github.com/foxyberry/agent-harness/pull/154)
  (the corrected section), PR [#155](https://github.com/foxyberry/agent-harness/pull/155), commit
  `c59a226`.
- Tests: `tests/test_session_decision_capture.py` pins the sourcing rule in core and in both
  rendered adapters.
