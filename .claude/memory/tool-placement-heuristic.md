---
name: tool-placement-heuristic
description: Placing a new hook or tool = generic data-driven engine → harness core / taste- or convention-dependent → personal ~/.claude (my habits) or a repo commit (team-shared). Keep the project-specific content out of core, not the hook itself
type: feedback
---

Use this rule instead of re-deriving the decision every time you place a new hook, skill or tool.

| Character | Location | Why |
|---|---|---|
| **Generic engine** (tool- and project-independent, driven by data) | harness **core/** → build.sh → shipped to the adapters | reusable for every installer. But do not hardcode "what to do" — keep it in project data ([[engine-data-separation]]) |
| **My personal habits** (how I work with this user, dependent on branch conventions) | personal **`~/.claude/hooks`** + settings | applies to all my repos immediately, no commit needed, not shared with the team |
| **Team rules** (teammates and other machines must follow too) | **committed to each repo** (`.claude/hooks` + settings, referenced relative to `$CLAUDE_PROJECT_DIR`, or git `.githooks`) | everyone who clones follows it. Work required in every repo you add it to |

**Why:** on 2026-07-23, with the PR-to-issue linking hook (and the signing hook before it), the
user kept asking the same question — "should this go in the harness or in each repo?" With no
decision rule, it was re-argued every time.

## Skills get filtered one step earlier (2026-08-17)

The table above decides "where to put it". Before that, ask **"is this harness work at all?"**

> If it deals with state the agent produced (session logs, memory, hooks), it is harness work.
> If it only deals with git and GitHub, it is a general tool — however useful, it does not
> belong here.

Five of them — `merge-cleanup`, `prettier-guard`, `stale-scan`, `review-ledger`,
`verify-regression` — did not pass this filter and moved to personal scope on 2026-08-17 (#105).
They all worked and were actually in use — **working is not the criterion.**

`verify-regression` was the borderline case. It catches an agent-specific failure: agents are
good at writing empty tests that only pass. It went out anyway. **One exception and the line
blurs again.**

**How to apply:**
- **Judging harness core**: if it depends on branch naming conventions or team taste, it is not
  core — that breaks the generic property. Hooks themselves do belong in core when they are
  generic, data-driven engines; the harness ships hooks to both Claude and Codex today, with
  Codex coverage still partial (`pr-merge-reflect` is registered only for SessionStart and
  PostToolUse/Bash — see `docs/codex-hooks.md`). What stays out of core is the project- or
  convention-specific *content*: put that in project data (`.claude/memory/*.json`) or in a
  personal / per-repo hook.
- **Personal vs repo commit**: "only I have to follow it" → personal. "teammates and other
  machines must follow it too" → commit to the repo (the way the signing hook was done).
- **When it is unclear, ask the user once** and let them pick personal / repo / harness (it is a
  recurring fork, so the check is worth it).
- When committing to a repo that has parallel work in progress, use a **git worktree** to stay
  non-invasive (do not touch another AI's working tree).

Related: [[engine-data-separation]], [[build-drift]]
