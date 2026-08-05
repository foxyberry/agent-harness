# Public release audit

Audit date: 2026-08-05

Tracking issue: [#71](https://github.com/foxyberry/agent-harness/issues/71)

## Current decision

**NOT READY**. Do not change repository visibility until the blocking decisions below are resolved
and the final scan is repeated.

## Checks completed

- `./build.sh` completed without core/adapter drift.
- `python3 -m unittest discover -s tests` passed all 83 tests before audit changes.
- Common token, private-key, credential, absolute-path, and local-home patterns were scanned in the
  current tree and Git patch history. No credential or private-key match was found.
- Tracked handoff files, repository URLs, author identities, open pull requests, branches, recent
  Actions runs, and release metadata were reviewed.
- Recent Actions runs pass and there are no open pull requests or published releases.

This was a targeted pattern scan, not a substitute for a dedicated scanner such as Gitleaks. Run a
dedicated full-history scan immediately before changing visibility.

## Blocking decisions

### License

The repository has no license. Choose and add a license before public release. Until then, external
users can read the source but do not receive permission to copy, modify, or redistribute it.

### Historical identity metadata

Git history contains a personal author email and committed handoffs contain a personal machine host
name. Removing the current files does not remove those values from history. Decide whether to:

1. preserve history and accept that metadata becoming public; or
2. rewrite history, force-push rewritten refs, and accept that existing commit and PR links change.

No history rewrite is performed as part of this audit without explicit approval.

## Changes prepared by this audit

- Handoff generation no longer reads the operating-system host name by default. Set
  `HARNESS_HANDOFF_MACHINE` only when an explicit non-sensitive label is desired.
- A security reporting policy is included. Enable GitHub private vulnerability reporting when the
  repository becomes public.
- Stale tracked handoff snapshots containing the host name are removed from the current tree.

## Before visibility change

- Add the selected license.
- Resolve the Git history identity decision.
- Run a dedicated full-history secret scan.
- Recheck GitHub issues, pull requests, comments, Actions logs, branches, and release assets for
  internal information.
- Update README and `docs/overview.html` wording that currently assumes a private repository.
- Verify Claude Code and Codex installation from an account without collaborator access.
- Obtain an independent Claude Code review and record its findings. The first CLI attempts during
  this audit authenticated successfully but stalled without producing review output.
