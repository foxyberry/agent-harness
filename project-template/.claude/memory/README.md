# .claude/memory — project memory (data layer)

This directory is the **data layer** of the harness hooks. The engine (skills and hooks) comes
from the `agent-harness` plugin; the per-project files here decide *what* gets injected and
warned about. It is the "data = project" side of the three-layer structure.

## Configuration files (what the engine reads)

| File | Hook that reads it | Role | If missing |
|------|--------------------|------|------------|
| `routes.json` | memory-search (PreToolUse edit/Bash) | edited file or shell command → memory to inject | no-op (nothing injected) |
| `reflection-rules.json` | reflection (PostToolUse Edit/Write/`apply_patch`) | new code → quality warning regexes | only the built-in TODO/FIXME rule |
| `_rejected.md` *(created automatically)* | reflect job + `/memory-update` | drafts already discarded → do not regenerate the same draft | discarded drafts come back next session |

`_rejected.md` is not in the template — `/memory-update` creates it, with a header, the first
time a draft is discarded. It is **gitignored**: a list of lessons you decided not to keep is
closer to work habits and mistake history, so it stays in the personal tier. Claude and Codex
in the same project read the same path, so both tools share it without committing it.

The enabled examples target Kotlin/Spring. **Adapt them to your project's language and rules.**

`reflection-rules.json` also contains a `react-async-timing` starter pack that is off by
default. Turn that pack's `enabled` to `true` only in a React project. Regex warnings are
timing-risk *candidates*, so confirm the real scope and verify with a test that reproduces
the ordering.

## Memory files (what routes.json points at)

The actual knowledge files referenced by the `memory` entries in `routes.json`, for example
`patterns/code-quality.md` and `decisions/git-workflow.md`. Write them as markdown with
frontmatter (name/description/type) and register each one on a line in `INDEX.md` (Codex falls
back to reading that index directly). The `/memory-update` skill maintains them.

Memory holds only **decisions, constraints and non-obvious patterns** that stay true for a long
time. Resume checkpoints, WIP, in-flight PRs and next actions are not memory. Hand those over
with `/handoff-save`, and only when you actually switch session, tool, machine or person. Do not
store current values you can recompute from the code or a command, such as line counts, test
counts or open-PR status.

## _pending/ (automatic retrospective drafts)

When you enable automatic retrospectives with `HARNESS_AUTO_REFLECT=1`, the reflect job analyses
the session transcript and collects promotion candidates as drafts in `_pending/*.md`. Review and
promote (or discard) them with `/memory-update`. It is off by default — installing the harness
alone never starts a background LLM job.

This automatic drafting runs on **Claude**. The Codex adapter currently ships only the merge
detection and queueing stages: it registers no `UserPromptSubmit` hook and does not bundle
`reflect.py`, so no LLM draft is generated there. See
<https://github.com/foxyberry/agent-harness/blob/main/docs/codex-hooks.md>.

The `.gitignore` in this directory excludes `_pending/` and `_rejected.md`, so unapproved drafts
and the discarded-draft log are not picked up by `git add .`. A file you have reviewed and promoted
to a top-level memory or to `decisions/` commits normally.

The ignore rule is not retroactive for `_pending/` files Git already tracks. If an existing project
has committed drafts before, review their content and then remove them from the Git index as well.

## Enabling automatic retrospectives (opt-in)

```bash
export HARNESS_AUTO_REFLECT=1   # on merge, generate retrospective drafts with claude -p (Claude)
```
Choose the backend with `REFLECT_BACKEND` (claude|deepseek|ollama, default claude).
