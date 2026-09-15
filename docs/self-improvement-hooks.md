# Self-improvement hooks

The harness adds a **self-improvement loop** around its skills. During work, hooks bring
relevant knowledge into context, flag patterns in newly written code, and queue a retrospective
after a merge. Reviewed lessons then become memory for future sessions.

```text
project-memory-index  →  memory-search  →  reflection  →  pr-merge-reflect  →  /memory-update
session-start index     before-action    after-edit      merge retrospective   promote and
                        context          warnings                              persist
```

Both adapters bundle **four hooks**: Claude in `plugins/harness/hooks/`, Codex in
`plugins/codex/hooks/`. Their capabilities differ. Claude registers the full loop. Codex's
`pr-merge-reflect` registers only **SessionStart and PostToolUse detection/queueing**;
UserPromptSubmit reminders and automatic LLM retrospectives remain deferred pending installed
runtime measurements ([#85](https://github.com/foxyberry/agent-harness/issues/85)). Codex hooks
also require **trust**: an untrusted hook is silently skipped, without an error or warning.
See [the Codex hook contract and measured behavior](codex-hooks.md).

## Design: engine in core, data in the project

Hook scripts are generic engines, reusable across tools and projects. Project-specific choices
about **what** to inject or warn about belong in the project's `.claude/memory/` data files,
not in core.

| Hook | Engine (core) | Data (project) |
|---|---|---|
| `project-memory-index` | Read the index and inject the shared memory list | `INDEX.md`, optional `index-load.json` |
| `memory-search` | Match file paths or shell commands and inject relevant memory | `routes.json` |
| `reflection` | Apply regular expressions and emit warnings | `reflection-rules.json` |
| `pr-merge-reflect` | Detect merges, apply exclusions, and manage the retrospective queue | Optional `reflect-skip.json` |

Missing index or route data makes the corresponding hook a quiet no-op. Without custom rules,
`reflection` retains its built-in TODO/FIXME warning. `pr-merge-reflect` requires a
`.claude/memory/` directory and otherwise does nothing; within a participating project it uses
built-in skip rules when no skip configuration exists. Example data lives in
`project-template/.claude/memory/`. Its Kotlin/Spring examples should be adapted to your project.

### Path conventions

In an installed plugin, **scripts and project data live in different places**:

- **Scripts:** `${CLAUDE_PLUGIN_ROOT}/hooks/`, inside the plugin installation. Helper scripts
  are co-located: `pr-merge-reflect` finds `reflect.py`, and `reflect.py` finds
  `compact_transcript.py`, relative to `dirname(__file__)`. The Codex hook bundle deliberately
  omits the LLM helpers.
- **Project data:** `<project>/.claude/memory/`, including routes, rules, memory, and `_pending/`
  drafts. Runtime queue caches and logs live separately under `<project>/.claude/.cache/`.

Claude supplies `CLAUDE_PROJECT_DIR`. Codex does **not** supply that variable; hooks resolve the
project from the input JSON's `cwd` and their fallback logic. Codex does supply
`CLAUDE_PLUGIN_ROOT` as a compatibility alias (measured with codex-cli 0.145.0). Do not use the
plugin installation directory as the project data directory.

### Project data crosses a trust boundary

This data comes from **the repository the user opened**. Hooks run around edits and shell
commands and put repository text into the agent's context, so the engine treats it as a trust
boundary:

- Injection is bounded by a **total character budget**, including file labels. Counting only
  file contents would let long filenames bypass the limit.
- Empty matching patterns are ignored; otherwise an empty substring would match everything.
- Injected memory identifies its source as **repository-provided reference material**, rather
  than instructions from the harness.
- Memory paths in `routes.json` must resolve inside `.claude/memory/`. Absolute paths and
  traversal or symlinks that escape that directory are rejected.

Retrospective drafts in `_pending/` and rejection records in `_rejected.md` contain material
extracted from conversations. The merge hook adds local exclusions for those paths and runtime
caches to `.git/info/exclude`, even if the optional project template was never copied. It does
not modify the repository's `.gitignore`, and it escapes gitignore metacharacters so the
exclusions protect the intended literal paths. These exclusions do not untrack files that have
already been committed.

## Hook details

### project-memory-index — shared memory discovery at session start

- **Event:** SessionStart.
- **Behavior:** read `.claude/memory/INDEX.md` and inject it as `additionalContext`. This makes
  shared rules, decisions, and retrospectives discoverable early in the session; it does not
  automatically load every memory file. Read individual files when relevant to the task.
- **Size limit:** 12,000 characters by default, with a truncation notice when needed.
- **Configuration:** `.claude/memory/index-load.json` can disable injection or change the limit.

```json
{
  "enabled": true,
  "max_chars": 12000
}
```

`enabled: false` disables automatic index injection. `max_chars` is clamped to 1,000–50,000.

### memory-search — relevant memory before an action

- **Event:** PreToolUse with `Edit|Write|MultiEdit|Bash` on Claude, `apply_patch|Bash` on Codex.
- **Behavior:** match the edited file paths or shell command against `routes.json`, then read
  matching memory files and inject them as `additionalContext` before the action.
- **Path safety:** project-controlled routes cannot inject arbitrary local files by escaping
  `.claude/memory/` through absolute paths, traversal, or symlinks.

Example `routes.json`:

```json
{
  "rules": [
    { "glob": "*.kt", "memory": ["patterns/code-quality.md"] },
    { "contains": ["batch", "etl"], "memory": ["decisions/issue-workflow.md"] },
    { "contains": ["git"], "match_empty": true, "memory": ["decisions/git-workflow.md"] },
    { "command_contains": ["gh pr create"], "memory": ["decisions/review-rule.md"] }
  ]
}
```

- `glob`: match file paths with Python `fnmatch`.
- `contains`: match any listed substring in a file path, case-insensitively.
- `match_empty`: also match an edit whose path could not be extracted.
- `memory`: paths relative to `.claude/memory/`.
- `command_contains`: match a substring in the **raw shell command**, case-insensitively.

**Path and command keys are separate.** `glob`, `contains`, and `match_empty` apply only to
edits; `command_contains` applies only to shell commands. Otherwise a path rule such as
`{"contains": ["hook"]}` would also inject memory on every read-only `grep -rn hook ...` call.

Command matching exists because some rules matter **when a command runs**, not when a file is
edited. For example, a project may require review evidence on the target thread before opening
a PR. Showing that rule only during edits misses the moment it is needed. This repository
missed the same rule three times before adding command routing
([#90](https://github.com/foxyberry/agent-harness/issues/90)). Knowing a rule and recalling it at
the right time are separate problems.

### reflection — quality warnings after edits

- **Event:** PostToolUse with `Edit|Write|MultiEdit` on Claude, `apply_patch` on Codex.
- **Behavior:** apply `reflection-rules.json` regular expressions to newly written content and
  inject warnings alongside the tool result. MultiEdit combines `edits[*].new_string`; Codex
  patches are normalized and checked per file.
- **Built-in rule:** warn about remaining TODO/FIXME markers in any language. Disable it with
  `"builtins": {"todo_fixme": false}`.

Example `reflection-rules.json`:

```json
{
  "rules": [
    { "glob": "*.kt", "regex": "!!",
      "message": "{count} uses of `!!` — consider requireNotNull or ?: return" },
    { "glob": "*.kt", "regex": "(?m)^\\s*var ", "min_count": 3,
      "message": "Many var declarations ({count}) — consider fold/associate/sumOf" }
  ]
}
```

Rule packs are opt-in. The engine does not know what a pack means: it appends the `rules` of
packs with `enabled: true` after the ordinary rules.

```json
{
  "rules": [],
  "packs": [
    {
      "name": "react-async-timing",
      "enabled": true,
      "rules": [
        {"globs": ["*.js", "*.jsx", "*.ts", "*.tsx"],
         "regex": "...", "message": "..."}
      ]
    }
  ]
}
```

The template's `react-async-timing` starter pack is **disabled by default**. In a React project,
enabling it flags possible side effects inside state updaters, missing completion signals in
catch blocks, render-time branches on `ref.current`, and collection resets at the beginning of
effects. Regular expressions cannot establish the AST or execution order, so a warning is a
candidate for investigation, not a bug verdict. Check the actual scope and reproduce pending
and rejection flows, account switches, and unmount/remount sequences with `renderHook` and
`rerender`.

- `glob`: one file pattern. `globs`: an array of patterns. Omitting both applies the rule to all
  files. Invalid types or an empty pattern array skip the rule instead of broadening its scope.
- `regex`: a Python `re` pattern. `enabled: false` disables that rule.
- `min_count`: emit only at or above this count; default 1.
- `message`: `{count}` is replaced with the match count.

An `Edit` checks only the replacement `new_string`, not the whole file. Multiline structures
that extend outside that fragment can be missed or flagged too broadly because of missing
context. `Write` checks the whole file. Neither is static analysis: these are prompts to verify
a concern. The starter pack's bounded regular expressions do not follow nested blocks, so the
absence of a warning does not establish safety.

### pr-merge-reflect — the merge retrospective loop

**Claude events:** PostToolUse `Bash`, SessionStart, and UserPromptSubmit.
**Codex events:** SessionStart and PostToolUse `Bash` only; detection and queueing are registered,
with installed-runtime verification still pending. Codex can also announce existing draft files
at SessionStart; this is separate from the deferred UserPromptSubmit merge reminder.

The hook has two roles:

**A. Reminders, without an LLM.** Queue merged PRs that need a retrospective. On Claude, the
next user prompt receives a reminder to use `/feedback-review` and `/memory-update`. This role
does not depend on automatic retrospective opt-in. Detection paths are SessionStart polling
(including external merges), PostToolUse after `gh pr merge` (**only after verifying MERGED
state**), and, on Claude, user statements indicating a merge during UserPromptSubmit. The first
SessionStart seeds the already-merged PRs rather than queuing the entire existing backlog.

**B. Automatic retrospective jobs, opt-in and disabled by default.** See below. Codex's hook
bundle omits `reflect.py`, so enabling the environment variable does not enable automatic LLM
jobs in that adapter.

#### Retrospective skip rules

To avoid a PR containing retrospective artifacts immediately creating another retrospective,
`pr-merge-reflect` excludes matching PRs from the pending queue and automatic PR retrospective
jobs.

The built-in path list covers artifacts the harness itself creates. A PR is skipped if all
relevant changed files match any of these patterns:

- `.claude/memory/**`
- `.claude/handoff/**`
- `.agents/skills/**`

It is also skipped if a PR label matches `skip-reflect` or `no-reflect`, or a commit message
contains `[skip reflect]`, `skip-reflect`, or `no-reflect`.

**`CLAUDE.md`, `AGENTS.md`, and `.gitignore` are not built-in exclusions.** Lessons can be
promoted into those files, but they belong to the project, and the significance of a change
varies. In this repository, an `AGENTS.md` change redefined the harness's scope (#105); elsewhere
it might be boilerplate. Hardcoding the broader list could silently discard a meaningful
retrospective.

The broader example is therefore project data in
`project-template/.claude/memory/reflect-skip.json`. Copy and adjust it as needed. A project that
adopted the template before this file existed does not have it; `/template-check` lists it as
missing.

```json
{
  "//": "Template example: only the first three path patterns are engine defaults.",
  "paths": [".claude/memory/**", ".claude/handoff/**", ".agents/skills/**",
            "CLAUDE.md", "AGENTS.md", "**/CLAUDE.md", "**/AGENTS.md",
            ".claude/agents/**", ".claude/skills/**"],
  "ignore_paths": [".gitignore", "**/.gitignore", ".gitattributes", "**/.gitattributes"],
  "labels": ["skip-reflect", "no-reflect"],
  "commit_messages": ["[skip reflect]", "skip-reflect", "no-reflect"]
}
```

- `paths`: skip when **all** relevant changed files match these `fnmatch` patterns.
  `**/AGENTS.md` matches nested paths, so list root `AGENTS.md` separately.
- `ignore_paths`: remove incidental files from the path-based decision. Otherwise one
  `.gitignore` change can break the “all files” condition and make an artifact-only PR look like
  ordinary work (#130). This list is **empty by default**: ignore and attributes changes can
  affect substantive tracking or line-ending policies, so the project must decide what is
  incidental. If removing these files leaves none, the path test does not skip the PR; there
  is no remaining evidence for that decision.
- `labels`: skip if any label matches, using case-insensitive `fnmatch`.
- `commit_messages`: skip if any listed substring occurs, case-insensitively.
- `"defaults": false`: clear the built-in defaults for **all keys**, using only project data.

These mechanisms already exist. Broader questions about which retrospective-generated rules
and documentation should be excluded remain tracked in
[#130](https://github.com/foxyberry/agent-harness/issues/130).

### reflect.py and compact_transcript.py — automatic retrospective jobs

In the Claude adapter, `pr-merge-reflect` can spawn a detached job that compresses a session
transcript, asks an LLM to analyze it, and writes durable lessons as **drafts** under
`.claude/memory/_pending/`. It can read both Claude `.jsonl` and Codex rollout files. It continues
running after the initiating session closes, and preserves duplicate slugs with numeric suffixes
rather than overwriting pending drafts. ADR drafts go in `_pending/decisions/`.

The Claude hook can also sweep eligible local Codex sessions at SessionStart when automatic
retrospectives are enabled. That is distinct from running an LLM job through Codex's own hook
adapter, which remains deferred.

Retrospective candidates use only segments beginning with a **user turn whose provenance is
accepted**. For Claude logs, positive evidence is a per-record `promptSource` of `typed`,
`queued`, or `suggestion_accepted`, or `origin.kind=human`. Older user turns without evidence
are excluded from the segment. Notifications and metadata injections are discarded individually;
explicit automation origins such as `sdk`, `system`, or a nonhuman `origin` also break trust in
the following assistant segment because it may be automation output.

If no positively attributed user turn remains, automatic retrospectives reject the candidate;
the strict compression CLI warns and exits with status 3. When only part of the transcript is
retained, stderr reports attributed and excluded turn counts. Codex logs lack equivalent
per-record provenance fields: the compactor trusts the `event_msg.user_message` channel and
discards `response_item` records with `role=user`, which can include injected context. This does
**not** provide the same per-record positive attribution guarantee as Claude.

Historical-session compression in `/feedback-review` and `/memory-update` uses this strict
mode too. The standalone `compact_transcript.py` CLI retains a best-effort fallback when run
without strict options, for compatibility.

## Automatic retrospectives are opt-in

Automatic retrospectives launch a **background LLM process or request** through `claude -p`,
DeepSeek, or Ollama. They are disabled by default so installing the plugin does not silently
start LLM work after every merge in every project.

```bash
export HARNESS_AUTO_REFLECT=1          # Claude hook: generate retrospective drafts automatically
export REFLECT_BACKEND=claude          # claude (default) | deepseek | ollama
```

Claude's reminders remain active regardless of this setting. With automatic jobs disabled,
use `/feedback-review` and `/memory-update` manually. Codex's deferred merge reminders and LLM
jobs are not enabled by these variables.

Review `_pending/` drafts with `/memory-update`, then **promote, merge, or reject** them.
Governance is explicit: `_pending → human approval → committed`. Draft generation never
establishes a committed memory or decision on its own.

Rejected drafts are recorded in `.claude/memory/_rejected.md` and supplied to future
retrospectives to discourage duplicate proposals. This is **not a ban list**: if repetition or
new evidence changes a lesson's value, it can be proposed again with an explanation of what
changed. It is prompt guidance rather than a guarantee that an LLM will never repeat a draft.

## Configuration summary

Here `<project>` means the resolved project directory, not the plugin cache.

| Purpose | Location | When absent |
|---|---|---|
| Shared memory index | `<project>/.claude/memory/INDEX.md` | Index hook does nothing |
| Index injection options | `<project>/.claude/memory/index-load.json` | `enabled=true`, `max_chars=12000` |
| File/command-to-memory routes | `<project>/.claude/memory/routes.json` | Memory search does nothing |
| Code quality rules | `<project>/.claude/memory/reflection-rules.json` | Built-in TODO/FIXME warning only |
| Retrospective skip rules | `<project>/.claude/memory/reflect-skip.json` | Built-in artifact paths, labels, and message markers |
| Rejected draft history | `<project>/.claude/memory/_rejected.md` | No rejection history supplied for deduplication |
| Automatic retrospective opt-in | Environment: `HARNESS_AUTO_REFLECT=1` | Claude reminders only; retrospective work is manual |
| Retrospective backend | Environment: `REFLECT_BACKEND` | `claude` |
| Hook entry tracing | Environment: `HARNESS_HOOK_TRACE=<file>` | No trace to distinguish a quiet run from no run |

The hooks fail open: missing project data or a recoverable hook error does not block the
session. The built-in TODO/FIXME warning can still run without custom project data.

## Known limitation of automatic jobs

When automatic retrospectives are enabled, the **Codex-session sweep records a successful
spawn as seen**, without waiting for job completion. If the detached `reflect.py` process or
its backend later fails because of PATH, timeout, or a nonzero exit, that session will not be
retried by the next sweep even if no draft was produced. Failure details go to
`.claude/.cache/reflect.log`. Recording completion through a callback remains follow-up work.
A failure to spawn at all does not mark the session seen, so the next sweep can retry it.

The earlier nested-code-fence truncation problem is fixed. ADR drafts can quote code as
evidence, so identical three-backtick inner and outer fences were ambiguous. The parser now
requires a closing fence at least as long as the opening fence, and the prompt uses four
backticks for outer draft fences.

## Validation status

- **Implementation and repository tests:** cover no-op behavior, route injection, regex rules,
  MultiEdit, path escape protection, duplicate-slug preservation, normalized Codex patches, and
  generated hook wiring. Review-driven fixes also gate SessionStart GitHub polling on the
  presence of `.claude/memory/`, strengthen merge detection and command matching, and handle
  malformed CLI input, transcript size, and path fallbacks.
- **Installed runtime measurements:** issues #3 and #103 recorded hook firing in a real project
  outside this repository. Hook-entry instrumentation (`HARNESS_HOOK_TRACE`) distinguishes
  “ran and had nothing to inject” from “never ran,” which tool logs alone cannot reliably do.
  Injection experiments compared the same question with hooks disabled and enabled while
  preventing the model from directly reading the canary file.
- **Scope of that evidence:** the historical measurements cover Claude's four hooks and Codex's
  index and edit hooks. They do **not** establish installed runtime behavior for the later
  Codex `pr-merge-reflect` detection/queue registration. That smoke test, UserPromptSubmit
  injection, and automatic LLM integration remain follow-up work under #85. See
  [current porting status](codex-hooks.md#current-porting-status).
