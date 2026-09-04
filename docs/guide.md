# Usage guide — what to reach for, and when

The other documents here explain **what was built**. This one explains **what you use, and
when**. It is written for someone who did not build the harness — or who built it and has
since forgotten.

- Design and structure → [overview.html](overview.html)
- How the hooks work internally → [self-improvement-hooks.md](self-improvement-hooks.md)
- Codex hook constraints → [codex-hooks.md](codex-hooks.md)
- Design for something not built yet → [decision-mining.md](decision-mining.md)

---

## 0. One paragraph

This harness reduces **what you lose when work is interrupted**. When a session ends, when
you switch tools, when you move to another machine, or when you come back after a few days,
you should not have to rediscover "what was I doing" and "I've hit this before" every time.

It does two things.

| | What |
|---|---|
| **Resuming** | Carries the state of in-progress work forward (`handoff-*`, `fw`, `history`) |
| **Memory** | Makes what you learned show up on its own in the next session (memory + hooks) |

Anything outside those two — branch cleanup, issue triage, ordinary git and GitHub chores —
is **deliberately left out.** A tool that works in any repository belongs in your personal
skills, not here.

---

## 1. By situation

### Handing work off, or picking it up

| Situation | Reach for |
|---|---|
| Stopping for today, continuing tomorrow | `/handoff-save` |
| Another machine or person has to continue | `/handoff-save` → commit |
| Picking up what someone (or yesterday's you) left | `/handoff-load` |
| **The session ended and you never saved** | `/fw` |
| You worked across both Claude and Codex | `/fw-both` |
| "Which session was that work in?" | `/history` |

**The difference between `handoff` and `fw` is the thing to understand.**

- `handoff-save/load` = a handoff file **a human deliberately saved**. It is committed, so
  **other machines and other people** can read it. This is the canonical record.
- `fw` = the rescue path for **when you didn't save**. It reconstructs from session logs
  (Claude `.jsonl` / Codex rollout). It works **only on the same machine**, and it is not
  committed.

So `fw` is for the "ah, I never saved" moment. Day to day, `handoff-save` is the right one.

`/history` restores nothing. It is **search only** — it lists and searches sessions, then
prints the command that hands your chosen session to `fw`.

### After the work is done

| Situation | Reach for |
|---|---|
| Decide whether this round's feedback should become a rule | `/feedback-review` |
| Persist what you learned into memory | `/memory-update` |

---

## 2. The seven skills

### The ones you reach for often

**`/handoff-save`** — saves the current state to a committable file: the branch, what you
stopped in the middle of, the next actions, and any open review findings.

```
/handoff-save unified the trade client, about 80% done
```

The one-line summary is optional, but write it. Later it is the only thing you see in a
list when choosing.

**`/handoff-load`** — reads the committed handoff first and **checks it against current git
state**. If the handoff is old, it says so. Reporting the state is where it stops by
default; verification, builds, and git operations have to be asked for separately.

**`/fw`** — recovers from session logs even when nothing was saved. It defaults to the
**opposite tool** (run it in Claude and it reads Codex logs). That default exists to stop
the current session from picking *itself* as "the previous work".

**`/memory-update`** — promotes what this session learned into memory. It separates the
personal and shared tiers; the shared tier needs a commit. Any waiting `_pending` drafts
are reviewed at the same time.

## 3. Why the unused skills went unused

Two reasons.

(An earlier version of this document had a third: "the situation never comes up in this
repository." That was about tools like `merge-cleanup` and `stale-scan`, and what it really
meant was that **they did not belong here**. They moved to personal skills on 2026-08-17.)

### (1) Not knowing they exist

`history` and `fw-both` fall here. The situation came up repeatedly — sessions were juggled
back and forth — and they simply did not come to mind. **That is a discoverability problem,
not a tool problem.** This document is the attempt to close it.

### (2) Automatic, so you never noticed using them

Hooks are **not commands.** They run on their own at session start, around file edits, and
on merges. Injecting the memory index, surfacing relevant memory before an edit, prompting
for a retrospective after a PR merges — all of that is hooks. It is not that you never used
them; **you were using them the whole time.**

**That said, this is the Claude story.** On Claude all four run. Codex bundles all four, but
`pr-merge-reflect` registers only detection and queueing, and every one of them runs only
once **you trust the hook** — before you do, they are skipped with no error and no warning.
The post-merge retrospective prompt and the automatic drafting are still being verified
([#85](https://github.com/foxyberry/agent-harness/issues/85)).

---

## 4. Memory — this is the core of the harness

### Two tiers

| | Location | Committed | Who reads it |
|---|---|---|---|
| **Personal** | `~/.claude/projects/<project>/memory/` | ✗ | Claude Code, this machine only |
| **Shared** | `<repo>/.claude/memory/` | ✓ | Claude and Codex both |

**Personal** is "how to work with me" — how to report, when to ask, commit signature rules.
**Shared** is "this project's facts and decisions" — why it was designed this way, what not
to do.

When it is unclear, ask. The fork is whether it is a personal preference or a team rule.

### How it surfaces on its own

```
session start   → the INDEX.md listing is injected whole (project-memory-index)  ← Claude and Codex
before edit/cmd → memory that routes.json points to is injected (memory-search)  ← Claude and Codex
after an edit   → regex quality warnings from reflection-rules.json (reflection) ← Claude and Codex
after a merge   → retrospective prompt (pr-merge-reflect)              ← Claude; Codex detect/queue only
```

**Codex has only the last line's detection and queueing registered** ([#85](https://github.com/foxyberry/agent-harness/issues/85)).
The edit hooks attach to Codex's `apply_patch`, and when one patch touches several files the
rules apply to **all of them**.

**Without `routes.json` the second line does not run at all.** Write a memory but attach no
route, and it exists only as one line in the session-start listing. That is why adding a
memory means adding its route in the same breath.

### Why `description` matters

The `memory-search` hook injects the **whole file**, so it never reads `description`. The
only place `description` is used is **that one line in `INDEX.md`** — and that line is all
you see at session start.

So the line cannot be an aphorism. There is one test: **"would this line alone make me open
the file?"**

```
❌ Keep recovery records outside what they recover     ← no sign of when the rule applies
✅ Cache and alias location: never inside a worktree, put it in the shared .git dir
```

### Governance

Shared memory goes through `_pending → human approval → committed`. It is the mechanism that
stops an automatically drafted lesson from landing unreviewed.

> Note: the automatic retrospective that fills `_pending` is **off by default**
> (`HARNESS_AUTO_REFLECT=1` opts in). Installing the plugin should not start a background LLM
> job. Because of that, `_pending` has never been produced in this repository, and every
> memory here was promoted by hand through `/memory-update`.

Drafts a human **rejected** are recorded in `.claude/memory/_rejected.md` so the same one
does not come back as a candidate. It is not a ban list — if the same point recurs until it
earns its place, raise it again with **what changed** attached.

`_pending/` and `_rejected.md` are **extracted from session conversations**, so committing
them wholesale is a problem. The hook engine therefore hides them itself by writing to
`.git/info/exclude` — so that someone who never copied `project-template/` is still
protected. Being a local exclude rather than `.gitignore` means it does not touch the
repository's own settings.

---

## 5. What to know before changing it

`core/` is canonical and `plugins/` is **generated**.

```
edit core/ → ./build.sh → plugins/harness (Claude) + plugins/codex (Codex)
```

**Edit an adapter directly and the next build overwrites it.** CI builds and then checks
`git diff` for drift, so committing without running the build fails.

Editing documentation changes no behavior. `docs/codex-hooks.md`, for instance, is only a
description — adding a hook to Codex means editing **`build.sh`**.

---

## 6. Current state (2026-08-31)

| | Claude | Codex |
|---|---|---|
| Skills | 7 | 7 |
| Hooks | all 4 | **4** (`pr-merge-reflect` at the detect/queue stage) |
| How they trigger | slash commands | `description` matching |
| Hook trust | not needed | **required** — without it they silently do nothing |

The user reminder and automatic drafting stages of the Codex merge hook open after the
installed-plugin smoke test ([#85](https://github.com/foxyberry/agent-harness/issues/85)).

`/feedback-review` only looking at the current session ([#81](https://github.com/foxyberry/agent-harness/issues/81))
is fixed — accumulated `_pending` drafts now always come in, and past or opposite-tool
sessions come in **only when a human selects them**.
