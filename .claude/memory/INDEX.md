# Project memory index — agent-harness

Shared (committed) memory. Claude reads this index at session start and then pulls the relevant
memory bodies in through the memory-search hook. Codex ships these hooks too: the bundled
`project-memory-index` hook injects this index at SessionStart and `memory-search` injects memory
bodies before edits — both were observed firing on Codex on 2026-08-15. Codex coverage is still
partial: `pr-merge-reflect` is registered for SessionStart and PostToolUse/Bash, but its install
measurement is still pending, and UserPromptSubmit injection plus the LLM job stay unregistered
(`docs/codex-hooks.md`). Registration is not the same as measured firing — whenever this index
was not injected for any reason (not installed, the plugin untrusted, a hook that did not run),
read it directly.

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
(The schema is in the `memory-update` skill §1.6, which ships with the plugin. No real ADR has
been promoted yet.)
