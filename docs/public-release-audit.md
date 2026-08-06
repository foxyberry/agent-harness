# Public release audit

Audit date: 2026-08-06

Tracking issue: [#71](https://github.com/foxyberry/agent-harness/issues/71)

## Current decision

**NOT READY**. Git history will be preserved with its existing identity metadata. Do not change
repository visibility until a license is selected and the final scan is repeated.

## Checks completed

- `./build.sh` completed without core/adapter drift.
- `python3 -m unittest discover -s tests` passed all 85 tests after audit changes.
- Common token, private-key, credential, absolute-path, and local-home patterns were scanned in the
  current tree and Git patch history. No credential or private-key match was found.
- Tracked handoff files, repository URLs, author identities, open pull requests, branches, recent
  Actions runs, and release metadata were reviewed.
- Recent Actions runs pass and there are no open pull requests or published releases.

This was a targeted pattern scan, not a substitute for a dedicated scanner such as Gitleaks. Run a
dedicated full-history scan immediately before changing visibility.

## Blocking decision

### License

The repository has no license. Choose and add a license before public release. Until then, external
users can read the source but do not receive permission to copy, modify, or redistribute it.

## Accepted exposure

Git history contains a personal author email and committed handoffs contain a personal machine host
name. The repository owner explicitly chose to preserve the existing history and accepts that this
metadata will become public. No history rewrite will be performed. The decision is recorded in
[issue #71](https://github.com/foxyberry/agent-harness/issues/71#issuecomment-5200286114).

## Changes prepared by this audit

- Handoff generation no longer reads the operating-system host name by default. Set
  `HARNESS_HANDOFF_MACHINE` only when an explicit non-sensitive label is desired.
- A security reporting policy is included. Enable GitHub private vulnerability reporting when the
  repository becomes public.
- Stale tracked handoff snapshots containing the host name are removed from the current tree.

## Before visibility change

- Add the selected license.
- Run a dedicated full-history secret scan.
- Recheck GitHub issues, pull requests, comments, Actions logs, branches, and release assets for
  internal information.
- Update README and `docs/overview.html` wording that currently assumes a private repository.
- Verify Claude Code and Codex installation from an account without collaborator access.
- Obtain an independent Claude Code review and record its findings. Completed: Claude Code confirmed
  the history metadata and missing license findings and found no regression in the audit changes.
  The result is recorded in
  [issue #71](https://github.com/foxyberry/agent-harness/issues/71#issuecomment-5200286253).
