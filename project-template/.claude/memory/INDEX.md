# Project memory index

The list of shared (committed) memories. Claude reads this index automatically at session
start and then pulls memory bodies in through the memory-search hook. Codex ships the same
hooks, but its coverage is partial — if this index was not injected at session start, read it
directly (the harness documents the Codex limits in
<https://github.com/foxyberry/agent-harness/blob/main/docs/codex-hooks.md>).
`/memory-update` adds one line here whenever it adds or updates a memory file.

- [code-quality](patterns/code-quality.md) — code quality rules (example — replace it)
- [git-workflow](decisions/git-workflow.md) — git workflow rules (example — replace it)

Configuration files:
- `routes.json` — maps edited files and shell commands to the memory to inject
- `reflection-rules.json` — regexes for post-edit quality warnings
- `reflect-skip.json` — skip rules for retrospective-output PRs

## Decision records (ADR — decisions/, schema in the `memory-update` skill §1.6)
Register each promoted ADR here on one line: `[<id>](decisions/<name>.md) — [chain: <chain>] <one line>`.
(See `decisions/adr-EXAMPLE-*.md` for the format — that example is not a real decision, so it is not listed here.)
