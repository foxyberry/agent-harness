# agent-harness

[![validate](https://github.com/foxyberry/agent-harness/actions/workflows/validate.yml/badge.svg)](https://github.com/foxyberry/agent-harness/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

*English · [한국어](README.ko.md)*

A reusable agent harness that ships handoffs, shared memory, retrospectives, and
review/cleanup workflows to **both Claude Code and Codex**. It is for people who pick work
back up in a different session or a different tool, and who want the lessons from merged
work to survive as project memory instead of evaporating with the transcript.

> 📖 **New here, or coming back after a while? Start with the [usage guide](docs/guide.md).**
> It is organized by situation — what to reach for and when. This README covers installation
> and the shape of the system; the guide covers actually using it.

## Install

### Claude Code

Run inside a Claude Code session.

```text
/plugin marketplace add foxyberry/agent-harness
/plugin install agent-harness@foxyberry
```

### Codex

Run in a terminal.

```bash
codex plugin marketplace add foxyberry/agent-harness
codex plugin add agent-harness@foxyberry
```

The public marketplace installs over anonymous HTTPS — no repository access or SSH key needed.

> **⚠️ Codex hooks only run once you trust them.** Codex skips untrusted hooks **with no
> message at all**, so the install looks successful while the hooks quietly do nothing.
>
> After installing, opening a Codex session shows a `Hooks need review` screen. Review the
> hook and trust it. You can revisit this any time with `/hooks` — if the `Active` column
> reads `0`, the hook is not running. Codex asks again whenever a plugin update changes the
> hook. If you only want the skills, you can leave hooks untrusted.
> Details: [docs/codex-hooks.md](docs/codex-hooks.md).

## Claude Code and Codex

Both adapters are built from the same `core/`, but they install and trigger differently.

### Platform differences

These are properties of the two tools. They are why `core/` has to be repackaged per adapter
rather than copied.

| | Claude Code | Codex |
|---|---|---|
| How skills trigger | slash commands (`/handoff-save`) | the model matches on the skill's `description` |
| Where scripts live | `bin/`, put on `PATH` when the plugin is enabled | bundled per skill under `scripts/` |
| Hook trust | install implies consent | **each hook is reviewed and trusted separately**, keyed by hash, re-asked when it changes |
| Edit tool seen by hooks | `Edit`, `Write`, `MultiEdit` | `apply_patch` — one patch covering possibly several files |
| Project path for hooks | `CLAUDE_PROJECT_DIR` | not provided; read `cwd` from the hook's stdin JSON |
| Plugin path for hooks | `CLAUDE_PLUGIN_ROOT` | same variable (Codex provides it as a compatibility alias) |
| Local marketplace | `/plugin marketplace add ./` | `codex plugin marketplace add ./` |

Because Codex picks skills by reading their `description`, a Codex-facing description has to
say **when to use the skill**, not just what it does.

### Porting status — not a platform limit

| | Claude Code | Codex |
|---|---|---|
| Skills | 7 | 7 |
| Hooks | 4 | **4** (`pr-merge-reflect` detection/queue phase) |

The edit hooks now run on Codex too. Codex delivers an edit as a raw `apply_patch` payload
rather than a file path plus new text, so a normalization step turns both shapes into the same
model. Codex now registers merge/session detection and shared-queue updates, pending an installed
smoke test; prompt injection and background LLM paths remain disabled until that test verifies them
([#85](https://github.com/foxyberry/agent-harness/issues/85)).

## Why this exists

- It does not stop at capturing state when a session ends. The loop runs from injecting
  memory *before* an edit through prompting a retrospective *after* a merge.
- Handoffs and memory are committed to Git rather than living in a local transcript, so work
  crosses tools, machines, and people.
- Automatically drafted lessons are not shared straight away — they go through
  `_pending → human approval → committed`.

## What you get

| Skill | What it does |
|---|---|
| `handoff-save` | Save the current state to a committable file before handing off |
| `handoff-load` | Resume by reading the committed handoff and diffing it against current Git state |
| `fw` | Recover unsaved work from the other tool's local session log |
| `fw-both` | Read Claude and Codex session logs together |
| `history` | Browse and search local sessions by time |
| `feedback-review` | Decide whether review feedback should become a project rule or a skill |
| `memory-update` | Promote `_pending` drafts to shared memory after human review |

## The self-improvement loop

Beyond the skills you invoke explicitly, hooks fire on their own and use project memory.

| When | Hook | What it does | Claude | Codex |
|---|---|---|---|---|
| Session start | `project-memory-index` | Injects `.claude/memory/INDEX.md` into context | ✅ | ✅ |
| Before an edit | `memory-search` | Injects memory relevant to the file being touched | ✅ | ✅ |
| After an edit | `reflection` | Quality warnings from project regex rules and TODO/FIXME | ✅ | ✅ |
| After a merge | `pr-merge-reflect` | Flags un-reflected PRs, optionally drafts a retrospective | ✅ | 🟡 detect/queue registered, smoke pending |

Codex registers the last hook only for SessionStart and Bash PostToolUse detection. Prompt delivery
and automatic drafts remain disabled until the installed-plugin smoke test verifies them
([#85](https://github.com/foxyberry/agent-harness/issues/85)).

The hook engines live in `core/` and are generic. *Which* memory to inject and *which* rules
to check is decided by data in the project's `.claude/memory/`. With no data the hooks are
silent no-ops. The automatic retrospective spawns `claude -p`, so it stays off until you set
`HARNESS_AUTO_REFLECT=1`.

[Hook details](docs/self-improvement-hooks.md) · [Codex hook constraints](docs/codex-hooks.md)

## Adopting it in a project

The plugin installs the shared machinery; `project-template/` supplies the per-repository
rules and example data.

1. Merge `project-template/AGENTS.md` into your project's canonical rules.
2. On Claude Code, keep the `@AGENTS.md` import in `CLAUDE.md`.
3. Adjust the route and reflection examples under `.claude/memory/` to your stack.
4. Merge the PR template and workflow under `.github/` with your existing CI rules.

Do not overwrite existing files wholesale. `AGENTS.md`, `CLAUDE.md`, and `.github/` are the
ones most likely to collide with rules you already have.

## Layout

| Layer | Location | Role |
|---|---|---|
| core | `core/` | Tool-agnostic source of truth: skills, scripts, memory and handoff formats |
| adapter | `plugins/harness/`, `plugins/codex/` | `core/` packaged for Claude and Codex |
| opinion pack | `project-template/`, `docs/` | Team workflow and example data you adopt selectively |

`core/` is canonical; the adapters are **generated** by `build.sh`. Editing an adapter
directly gets overwritten on the next build, and CI fails the diff.

## Updating

```bash
# Claude Code
claude plugin marketplace update foxyberry

# Codex — there is no `plugin update` yet, so refresh the snapshot and re-add
codex plugin marketplace upgrade foxyberry
codex plugin remove agent-harness@foxyberry
codex plugin add agent-harness@foxyberry
```

**Close your Codex sessions first.** Codex deletes the old version's cache directory when it
installs a new one, and a session that is already running keeps pointing at the deleted path. Its
hooks then fail, and until Codex is restarted **it cannot run shell commands at all** — a real
`gh` command was refused this way on 2026-08-17. Restarting clears it; nothing is lost. Claude Code
keeps its old version directories, so its sessions survive an update.

From 0.8.1 onward the hooks absorb this themselves, so the warning applies to sessions started on
an earlier version. Details in [docs/codex-hooks.md](docs/codex-hooks.md).

You do not need to do this often — only when a new release lands.

## Development

Regenerate the adapters after touching `core/`.

```bash
./build.sh
python3 -m unittest discover -s tests
```

CI checks JSON manifest syntax, Python syntax, the test suite, and that `core/` and the
generated adapters are in sync.

## Status

- Plugin version: `0.11.0`
- Public marketplace installation verified for both Claude Code and Codex
- 7 skills on both adapters; cross-tool handoff verified (saved by one, loaded by the other)
- Hook firing and context injection verified — the same question was asked with hooks off and
  on, so an answer read straight from the file could be ruled out
- Codex ships four hooks; `pr-merge-reflect` is registered for detect/queue only until its
  installed-plugin smoke test completes

## Documentation

| Document | For |
|---|---|
| [docs/guide.md](docs/guide.md) | **Start here** — what to use, and when |
| [docs/overview.html](docs/overview.html) | Illustrated design overview |
| [docs/self-improvement-hooks.md](docs/self-improvement-hooks.md) | How the hooks work |
| [docs/codex-hooks.md](docs/codex-hooks.md) | Codex hook contract and constraints |
| [AGENTS.md](AGENTS.md) | This repository's own rules |

## Security, license, contributing

- Report vulnerabilities through the private channel in the [security policy](SECURITY.md),
  not a public issue.
- Released under the [MIT License](LICENSE).
- Discuss changes in an issue before opening a PR.
