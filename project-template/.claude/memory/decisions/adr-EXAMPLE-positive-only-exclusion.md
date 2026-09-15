---
name: adr-EXAMPLE-positive-only-exclusion
description: (example ADR — replace with a decision from your project) make fw-both session exclusion positive-only
type: decision
id: adr-20260715-001
chain: tool-switch-fw
status: active
supersedes: []
keywords: [fw-both, session-exclusion, positive-only, CODEX_THREAD_ID, self-selection-guard]
commit: d6eea9a
---

> This file is an **example ADR that shows the schema**. Replace it with a real decision from your
> project. (The content is a real decision made in this harness, so the format reference is genuine.)

## Context
`fw-both` shows session logs from both Claude and Codex, but the **live session of the tool that
just invoked the command** (the session you only now opened) must not be mistaken for "the previous
work". The problem was that the session-identifying env var Codex exports (`CODEX_THREAD_ID`) could
not be confirmed from logs alone to be the same as `session_meta.id` in the rollout.

## Decision
Exclude a session **only when the env identifier actually matches a real log in this project**
(positive-only). If it does not match, **hide nothing.**

## Alternatives
- **"Exclude the newest session when the env does not match" (fallback)** — rejected. When that newest
  session is in fact the previous work you need to restore, this hides it. It revives exactly the bug
  the first round of Codex review caught, so it was dropped.
- **Trust the env value as-is (exclude without cross-checking)** — rejected. While we cannot confirm what
  the env points at, this can exclude the wrong session or quietly have no effect at all.

## Consequence
- (Good) It is safe even without knowing the exact meaning of the env var — exclusion happens only on a match.
- (Accepted cost) In the worst case the current live session shows up as one extra line in the list. Picking
  work back up is **driven by current git first**. We accept that extra entry to avoid hiding work
  that must be restored.

## Evidence
- Commit `d6eea9a`, PR #13 (Closes #6).
- Five rounds of Codex code review (env name → version → positive-only → or short-circuit → clean).
- Related memory: verify-other-tool-runtime-ids (do not guess another tool's identifiers).
