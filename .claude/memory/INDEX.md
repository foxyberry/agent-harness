# Project memory index — agent-harness

Shared (committed) memory. Claude and Codex use `project-memory-index` at SessionStart and
`memory-search` before matching edits or shell commands. Since plugin 0.15.1, context uses only
`hookSpecificOutput.additionalContext`: on Codex 0.160.0 the old dual-key output failed, while
the fixed output delivered memory bodies and reflection warnings as developer context
([#167](https://github.com/foxyberry/agent-harness/issues/167), `docs/codex-hooks.md`).
Since 0.15.2, `pr-merge-reflect` also delivers UserPromptSubmit reminders after SessionStart or
PostToolUse/Bash queueing (verified in an isolated installation). Since 0.16.0, Codex
automatic drafts use prior idle interactive sessions, snapshots and shared worker locks;
they are enabled by default since 0.16.1. Registration is not proof of injection: if the index or
needed memory bodies have not arrived (an older plugin, missing trust, or an unmatched route),
read the relevant files directly. Do not assume an installed plugin has the current source.

- [engine-data-separation](engine-data-separation.md) — core/hooks is a generic engine; "what to do" lives in project data. No hardcoding
- [hooks-live-dir-gotcha](hooks-live-dir-gotcha.md) — when the plugin root is a live working copy, hook edits hit other running sessions; build.sh guards missing scripts, older sessions do not
- [build-drift](build-drift.md) — core is the source of truth; after editing core always run ./build.sh and commit the generated output too
- [plugin-release-updates](plugin-release-updates.md) — bump the Claude and Codex manifest versions together and ship the update instructions as one release unit
- [adapter-cross-project-testing](adapter-cross-project-testing.md) — verify adapter behavior and public installation with the repo, credentials and caches isolated
- [skill-command-examples](skill-command-examples.md) — put a required SKILL.md argument in the copy-pasted command example itself, not in a footnote
- [tool-placement-heuristic](tool-placement-heuristic.md) — placing a new hook or tool: generic data-driven engine → harness core; taste- or convention-specific behavior → personal ~/.claude or a repo commit
- [review-evidence-on-target-thread](review-evidence-on-target-thread.md) — leave external review results on the target PR or issue thread, as the original text or a link
- [committed-artifact-env-leak](committed-artifact-env-leak.md) — never auto-insert hostnames or absolute paths into committed artifacts; the default is `undisclosed`, with an environment-variable opt-in
- [squash-merge-consequences](squash-merge-consequences.md) — squash merge makes branch --merged useless; a stacked PR needs a rebase once its base is merged
- [cache-must-outlive-target](cache-must-outlive-target.md) — where to store a cache or alias: not inside a worktree or session; worktree state goes under the shared .git directory
- [no-absolute-time-in-fixtures](no-absolute-time-in-fixtures.md) — no absolute timestamps in test fixtures for code that looks at a recency window; once the date passes, CI breaks with no code change
- [close-the-issue-close-the-doc](close-the-issue-close-the-doc.md) — if you wrote down a "known bug / unverified / limitation", fix the doc in the same PR that closes that issue

## Decision records (ADR)

Register each promoted ADR on one line: `[<id>](decisions/<name>.md) — [chain: <chain>] <one line>`.
(The schema is in the `memory-update` skill §1.6, which ships with the plugin.)

- [adr-20260922-001](decisions/fetch-full-commit-messages-on-truncated-headline.md) — [chain: commit-message-parsing] On a truncated `gh pr view` headline, refetch full commit messages once from the REST endpoint and match by SHA; keep the truncated form on failure
- [adr-20260922-002](decisions/capture-decisions-in-the-interactive-retrospective.md) — [chain: decision-capture] `/memory-update` extracts decision candidates from the session itself, because the only draft writers are off by default or surfaced by no command
- [adr-20260922-003](decisions/alternatives-must-be-sourced-not-invented.md) — [chain: decision-capture] An ADR's `## Alternatives` must cite a real rejected option; with none stated the candidate fails the gate instead of being filled in
- [adr-20260923-001](decisions/select-typed-codex-input-by-content-kind.md) — [chain: codex-log-attribution] Keep the Codex `role=user` items whose `content_item_kinds` list `user.text`, only in a `codex-tui`/`cli` session, instead of excluding known injection wrappers
- [adr-20260929-001](decisions/template-check-compares-without-copying.md) — [chain: template-drift] `/template-check` only compares an explicitly named project against the bundled memory template and never writes, because a difference is often an intentional customization
- [adr-20260929-002](decisions/reflect-skip-stays-project-config.md) — [chain: retrospective-skip] The retrospective skip list stays per-project config with engine defaults unchanged; this repository adopts only the root `.gitignore` exception
