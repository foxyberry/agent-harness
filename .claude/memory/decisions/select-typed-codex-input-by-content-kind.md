---
name: select-typed-codex-input-by-content-kind
description: Read a Codex rollout's typed user input by keeping the role=user items whose content_item_kinds list user.text, and only in a session a person types into, rather than by excluding known injection wrappers
type: decision
id: adr-20260923-001
chain: codex-log-attribution
status: active
supersedes: []
keywords: [Codex rollout, content_item_kinds, user.text, attribution, compact_transcript, retrospective, codex-tui, injection, event_msg.user_message]
commit: 665672c
artifacts:
  - path: core/hooks/compact_transcript.py
  - path: tests/test_codex_typed_input.py
---

## Context

Strict retrospective mode accepted a Codex user turn only from an `event_msg.user_message` record.
Codex stopped writing that record: six rollouts from 0.154.0 carried zero of them while holding 1
to 57 `role=user` items each. With no attributed user turn the compactor exits 3, so every
retrospective on Codex work read an empty transcript (#147). The `role=user` items do hold the
typed words, but they also hold the AGENTS.md body, `<environment_context>` blocks and other
injected context, and reading those as user speech would let the project's own rules re-enter as
lessons.

## Decision

From cli_version 0.153.4 each `role=user` item declares what it carries in
`payload.internal_chat_message_metadata_passthrough.content_item_kinds`. Keep the items whose
kinds include `user.text`; ignore every other kind. Read this channel only in a session a person
types into — `originator: "codex-tui"` with `source: "cli"`. Logs without the field stay unread.

## Alternatives

- **Exclude injections by their wrapper prefix.** This is what issue #147 proposed: treat text
  starting with `<environment_context>`, `<user_instructions>` or `# AGENTS.md instructions for`
  as injected and the rest as typed. Rejected: a blocklist fails toward reading an unknown wrapper
  as speech, and the same file already records two rounds of that failure on the Claude side, where
  `_INJECTED_HEADS` had to grow after `<command-message>` was missed. The kinds field decides the
  same question by what Codex already labeled. (Issue #147 "제안" section;
  `_INJECTED_HEADS` comment in `core/hooks/compact_transcript.py`.)
- **Repair the `event_msg.user_message` channel alone.** Rejected by measurement: that record does
  not exist in 0.154.0 logs, so any fix resting on it still reads nothing. It is kept as the first
  channel because the mcp-mode logs do populate it. (Comment on issue #147.)
- **Accept `user.text` in every Codex session.** Rejected: `codex exec` carries the prompt a
  delegating agent wrote, a subagent thread carries its parent's prompt, and the `Claude Code`
  originator is Claude driving Codex — 264 items across the local corpus, including 56 copies of
  the code-review request the companion script sends. All three use the same `user.text` slot.
  (Measured 2026-09-23 over 172 rollouts; PR #158 description.)

## Consequence

Retrospectives can read recent Codex sessions: the three interactive logs for this repository
yield 69 typed items, and one 0.154.0 log compacts to 50 user turns with no injection among them.
`fw`, `fw-both`, `handoff-load` and `history` compact in recovery mode, so they show typed Codex
input as well — a behavior change in four skills the issue does not name. The accepted costs:
logs at 0.148.0 and below remain unreadable, because nothing in them separates typed input from
injected context; `codex exec` and subagent sessions are never read, so work delegated that way
produces no retrospective material; and the rule depends on a field Codex is free to rename, which
would return the compactor to reading nothing rather than to reading injections.

## Evidence

- Issue [#147](https://github.com/foxyberry/agent-harness/issues/147) and its measurement comment,
  PR [#158](https://github.com/foxyberry/agent-harness/pull/158), commit `665672c`.
- Corpus measurement, 2026-09-23, 172 local rollouts: 506 items carry `user.text`, none of them
  also carries an injection kind; the field first appears at 0.153.4 and is absent at 0.148.0 and
  below.
- Tests: `tests/test_codex_typed_input.py` — 10 subtests fail with the compactor reverted.
