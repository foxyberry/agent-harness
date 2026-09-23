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

It is also skipped if a PR label matches `skip-reflect` or `no-reflect`, or if any commit in the PR
**carries** `[skip reflect]`, `skip-reflect`, or `no-reflect` as a directive — see
[Where a commit marker counts](#where-a-commit-marker-counts) for the two positions that count.

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
- `commit_messages`: skip if any commit in the PR carries one of these as a **directive**,
  case-insensitively. Position matters — see below.
- `"defaults": false`: clear the built-in defaults for **all keys**, using only project data.

#### Where a commit marker counts

A marker is read as a directive in exactly two positions:

1. **anywhere in the subject** (the commit's first line) — the familiar `[skip ci]` convention:
   `docs: promote lesson [skip reflect]`; or
2. on a **standalone body line** whose entire content is the marker:

   ```
   docs: promote lesson

   Closes #130.

   [skip reflect]
   ```

**In the body, prose is ignored**: a sentence that mentions the marker, a backticked mention on its
own line, a `> ` quoted line and a fenced example all leave the PR reflectable. A fenced block ends
only at a line with the **same fence character**, a run **at least as long** as the opener and
nothing but whitespace after it, so `~~~` inside a ` ``` ` block, ` ``` ` inside a ` ```` ` block,
and ` ``` not a closing fence ` do not release it; a fence that is never closed hides the rest of
the body.

**In the subject there is no prose exemption** — that is the cost of following the `[skip ci]`
convention. `docs: document [skip reflect] positions` skips, even though the sentence is only
talking about the marker. The one exception is an exactly backticked occurrence
(``docs: explain `[skip reflect]` ``), which is a quotation. Writing about a marker in the subject
is rare; writing about one in a body is what PR #134 did. Nothing here infers intent from natural
language.

Matching is case-insensitive, and non-bracketed markers still need word boundaries, so
`no-reflection` does not trigger `no-reflect`. Patterns are used exactly as configured: a pattern
stored with padding (`"  [no-retro]  "`) keeps the padding, so it can match in the subject but
never equals a trimmed standalone body line.

**Long subjects (since 0.14.0).** `gh pr view` shortens a long headline mid-character
and moves the rest into the body (`[ski…` / `…p reflect]`), which split the marker
([#148](https://github.com/foxyberry/agent-harness/issues/148)). When a headline comes back
shortened, the hook now fetches the full messages once from
`gh api repos/{owner}/{repo}/pulls/<n>/commits?per_page=100` and uses them only for commits whose
SHA it lists. If that call fails, or does not list the commit, the shortened form is kept, so a
marker split by the cut can still be missed; other markers, labels and path rules still apply.

Separately, and unchanged by this: `gh pr view --json commits` returns only a PR's first 100
commits, so commits after the 100th are not checked for markers at all.

This is narrower than the original rule, which matched the markers as plain substrings anywhere in
the message. That inverted the feature: PR
[#134](https://github.com/foxyberry/agent-harness/pull/134) — the PR that introduced these rules,
16 files of hook engine, adapters, skills and docs — skipped its own retrospective because one body
line *explained* `[skip reflect]`. A silently lost retrospective is the failure this rule set exists
to prevent.

**The narrowing applies to project-supplied `commit_messages` patterns too, not only the
defaults.** Position, not pattern, is what separates a mark from a mention; a split rule would leave
a project's own `[no-retro]` carrying the bug while the built-in marker is immune. Every position
that still skips is one the old substring rule also matched, so the compatibility cost is
one-directional: a project that relied on its pattern matching mid-body-prose now gets **more**
retrospectives, never fewer. `tests/test_reflect_marker_intent.py` pins both directions against all
three engine copies.

#### Adopting the skip rules in an existing project

**A plugin update never adopts this configuration.** The plugin ships the engine and a read-only
reference copy of the template's `.claude/memory/`; it does not write into a project. A project
that adopted `project-template/` before `reflect-skip.json` existed keeps the engine defaults —
memory-only PRs are skipped, a memory PR carrying one `.gitignore` line is not — until someone
copies the file in. That is per-project opt-in by design ([#132](https://github.com/foxyberry/agent-harness/issues/132)),
not an oversight.

The manual recipe, which never overwrites an existing file:

1. Run `/template-check` in the project. It reports a status per reference file and prints the
   **reference directory**; a file's reference copy is that directory joined with the path after
   the leading `.claude/memory/`. `/template-check` ships from 0.13.0; on an older install, update
   the plugin first or use `project-template/.claude/memory/reflect-skip.json` from a source
   checkout as the reference.
2. **missing** — copy the reference to `.claude/memory/reflect-skip.json`, then edit it. The
   template's `paths` list is one project's judgement, not a default.
3. **differs** — do not overwrite. Merge by key. The loader **extends** the engine defaults, so a
   key you omit keeps its default instead of emptying; `"defaults": false` is the explicit opt-out
   that clears every key first. If the project already set `"defaults": false`, that is a
   deliberate decision — keep it, and merge the template's values into the project's own lists
   rather than reinstating the defaults.
4. **skipped** — the file was not compared, so there is nothing to act on. Do not copy over it;
   fix the reason the check could not read it first.
5. Decide `paths` deliberately. Skipping `AGENTS.md` or `CLAUDE.md` means a rule change gets no
   retrospective and says so nowhere. Where a rule document is boilerplate, adopt it; where a rule
   change can redefine what the project is, leave it out and mark the occasional
   retrospective-output PR with `[skip reflect]` in the commit **subject** (or on its own body
   line) or a `skip-reflect` label — both are engine defaults needing no configuration.
6. `ignore_paths` fixes the reported loop and is empty in the engine. List only files that are
   incidental **in this project**, and prefer exact paths: a `**/.gitignore` glob also matches
   ignore files that are shipped or generated content, and removing those from the verdict hides
   real changes.

This repository's `.claude/memory/reflect-skip.json` adopts `ignore_paths` only, and only the root
`.gitignore`. The nested ignore files under `project-template/` and `plugins/*/…/template-reference/`
are shipped or generated product, so they stay in the verdict. `AGENTS.md` and `CLAUDE.md` are left
out for the reason above — [#105](https://github.com/foxyberry/agent-harness/issues/105) was an
`AGENTS.md` change that narrowed the harness's scope, and `project-template/AGENTS.md` ships to
users — so a rule-promotion PR here uses the commit marker.
`tests/test_reflect_skip_adoption.py` pins the resulting matrix against the committed file,
separately from the generic engine and template layers in `tests/test_reflect_skip_scope.py`.

Still open: every other project that adopted the template early has to run the recipe above by
hand, which is what [#132](https://github.com/foxyberry/agent-harness/issues/132) and
[#130](https://github.com/foxyberry/agent-harness/issues/130) track.

The markers used to be matched as plain substrings anywhere in a commit message, so a commit that
merely *wrote about* `[skip reflect]` skipped its own PR — PR #134 did exactly that. They are now
read only in the two directive positions described in
[Where a commit marker counts](#where-a-commit-marker-counts).

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
retained, stderr reports attributed and excluded turn counts.

Codex logs are read through two positive channels. The first is the `event_msg.user_message`
record, which is unambiguous wherever it appears — but it is absent from recent interactive
sessions: six rollouts written by Codex 0.154.0 carried zero such records while holding 1 to 57
`role=user` items each ([#147](https://github.com/foxyberry/agent-harness/issues/147)). The
second covers those logs. From cli_version 0.153.4 onward every `role=user` item declares what it
carries in `payload.internal_chat_message_metadata_passthrough.content_item_kinds`, and the
compactor keeps the items listing `user.text` while ignoring every other kind
(`agents_md.instructions`, `environments.environment_context`, `plugins.recommendations`,
`unknown`). Measured over 172 local rollouts, 506 items carry `user.text` and none of them also
carries an injection kind. This channel is read only in a session a person types into
(`originator=codex-tui` with `source=cli`); `codex exec`, a subagent thread and the `Claude Code`
originator put another agent's prompt in the same slot. Logs at 0.148.0 and below carry no
`content_item_kinds`, so their `role=user` items stay unread — nothing in them separates typed
input from injected context.

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
