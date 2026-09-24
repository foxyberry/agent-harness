---
name: fetch-full-commit-messages-on-truncated-headline
description: When gh pr view truncates a commit subject, refetch the full messages once from the REST commits endpoint and match them by SHA, keeping the truncated form if that fetch fails
type: decision
id: adr-20260922-001
chain: commit-message-parsing
status: active
supersedes: []
keywords: [gh pr view, truncation, REST commits endpoint, skip reflect, commit message, SHA matching, pr-merge-reflect]
commit: c5f2ab7
---

## Context

`pr-merge-reflect` reads a merged PR's commit messages to decide whether a retrospective was
waived, and the directive `[skip reflect]` is only honored in the subject or on a standalone body
line. Those messages came from `gh pr view --json commits`, which cuts a long subject at a
**character** boundary and moves the rest into the body, putting `…` (U+2026) on both sides of the
cut. A real case, PR 445 of another (private) repository, arrived as `"[ski…"` / `"…p reflect]"`,
so the marker never matched and the merged PR kept being asked for a retrospective (#148).

## Decision

When a headline comes back truncated, fetch the PR's full commit messages once from
`gh api repos/{owner}/{repo}/pulls/<n>/commits?per_page=100`, and use a fetched message only for a
commit whose SHA it lists. If the fetch fails or omits that commit, keep the truncated text.

## Alternatives

- **Rejoin the two halves at the `…`.** This is what issue #148 proposed. Rejected: a rejoin cannot
  tell a cut subject from a body that legitimately begins with `…`, and guessing wrong promotes
  body prose into subject position — where, unlike the body, there is no prose exemption.
  (PR #152 description.)
- **Paginate the REST endpoint.** Rejected: `gh pr view --json commits` itself returns only a PR's
  first 100 commits, and the first REST page of 100 lists the same commits, so later pages could
  only add commits the verdict never sees, while a failure on a later page would discard the page
  already in hand. (`_full_commit_messages` docstring in `core/hooks/pr-merge-reflect.py`.)

## Consequence

Markers in long subjects match again. The accepted costs: one extra API round-trip (up to 8s) on
PRs with a truncated headline, and a silent degradation path — when the fetch fails the code
proceeds with the truncated text, so the marker can still be missed with no error surfaced. The
pre-existing 100-commit ceiling is unchanged and is now stated in `docs/self-improvement-hooks.md`.

## Evidence

- Issue [#148](https://github.com/foxyberry/agent-harness/issues/148), PR
  [#152](https://github.com/foxyberry/agent-harness/pull/152), commit `c5f2ab7`.
- Tests: `tests/test_reflect_marker_intent.py` (24 of its cases fail with the hook reverted).
