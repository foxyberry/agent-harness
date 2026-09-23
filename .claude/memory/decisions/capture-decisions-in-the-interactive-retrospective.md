---
name: capture-decisions-in-the-interactive-retrospective
description: Let /memory-update extract decision candidates from the session itself and route them to the ADR promotion step, instead of only promoting draft files written by something else
type: decision
id: adr-20260922-002
chain: decision-capture
status: active
supersedes: []
keywords: [ADR, decision capture, memory-update, feedback-review, _pending/decisions, mine.py, HARNESS_AUTO_REFLECT, retrospective]
commit: c59a226
artifacts:
  - path: core/skills/memory-update/SKILL.md
  - path: core/skills/feedback-review/SKILL.md
---

## Context

The ADR schema shipped with the plugin in #137, and `memory-update` §1.6 could promote a draft into
`.claude/memory/decisions/`. Three weeks later this repository had recorded zero decisions, because
nothing reached §1.6. Only two things write drafts: `reflect.py`, whose automatic retrospective is
gated behind `HARNESS_AUTO_REFLECT=1` and off by default, and `mine.py`, a CLI no skill or command
surfaces. The interactive retrospective — the path people actually run — collected `feedback`,
`project` and `reference` only, so a session that made a clear decision produced no candidate even
when the user asked for a retrospective (#153).

## Decision

`memory-update` §2 gains a `decision` category. A choice with a stated rejected option, a reversed
direction, or a choice that is expensive to undo becomes a candidate extracted from the session and
routed to §1.6, which now names its two inputs — draft files and session candidates — and says the
draft-deletion step applies only to files. `feedback-review` hands a decision to `memory-update`
instead of promoting it as a rule.

## Alternatives

- **Store decisions as ordinary `feedback` or `project` memory.** Rejected: those tiers have no
  `chain`, no `supersedes` and no INDEX entry, so a decision stored that way can never be
  superseded later. (PR #155 description.)
- **Rely on backward mining and surface `mine.py` as a command.** Rejected as the primary path:
  running it over the last 10 commits produced a draft whose two rejected alternatives appear in
  no cited source, because `mine.py` reads commit messages and not PR bodies. The session that made
  the decision knows the real rejected option; a commit message written afterwards usually does
  not. (Issue #153 body, path 3, and the diagnosis comment on #153.)

A third option, turning automatic forward capture on by default, was **not** decided. Issue #153
listed revisiting `HARNESS_AUTO_REFLECT` under "Suggested direction (not decided)", and the opt-in
stands for its original reason in AGENTS.md: installing the plugin must never start a background
LLM job. The interactive path carries forward capture instead.

## Consequence

The path people run can now produce ADRs; this decision record is the first one promoted through
it. The accepted costs: capture still depends on someone invoking `/memory-update`, and `mine.py`
remains unsurfaced by any command — and unavailable to Codex entirely, since it ships in the Claude
adapter only, so Codex has interactive capture but no backward mining.

## Evidence

- Issue [#153](https://github.com/foxyberry/agent-harness/issues/153) and its diagnosis comment,
  PR [#155](https://github.com/foxyberry/agent-harness/pull/155), commit `c59a226`.
- Released to users in 0.14.0 (#156); before that the installed 0.13.0 cache still ran the old text.
- Tests: `tests/test_session_decision_capture.py` — 12 subtests fail with the skill changes
  reverted.
