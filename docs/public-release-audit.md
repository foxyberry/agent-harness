# Public release audit

Audit date: 2026-08-06

Tracking issue: [#71](https://github.com/foxyberry/agent-harness/issues/71)

## Current decision

**READY FOR VISIBILITY CHANGE**. Git history will be preserved with its existing identity metadata,
and the repository will use the MIT License. The final repository and GitHub surface scans found no
secret or credential exposure.

## Checks completed

- `./build.sh` completed without core/adapter drift.
- `python3 -m unittest discover -s tests` passed all 85 tests after audit changes.
- Common token, private-key, credential, absolute-path, and local-home patterns were scanned in the
  current tree and Git patch history. No credential or private-key match was found.
- Tracked handoff files, repository URLs, author identities, open pull requests, branches, recent
  Actions runs, and release metadata were reviewed.
- Recent Actions runs pass, PR #72 is the only open pull request, and there are no published
  releases.
- Gitleaks 8.30.1 scanned the branch history and found no leaks. A separate working-tree scan covers
  the uncommitted final files before commit.
- Issue and pull request bodies, issue comments, review comments, and the 10 most recent Actions logs
  were checked for credential and local-identity patterns. One local path in merged PR #42 was
  replaced with `<repo>`; the repeated scan found no remaining match outside the accepted Git
  identity metadata.

The targeted pattern scan and a dedicated Gitleaks full-history scan both completed.

## Resolved decisions

### License

The repository owner selected the MIT License. The root `LICENSE` grants permission to use, copy,
modify, and redistribute the project under its terms.

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

## Visibility change and post-change verification

- Merge PR #72, rerun the branch-history scan at the resulting commit, and then change repository
  visibility.
- Enable GitHub private vulnerability reporting.
- Verify Claude Code and Codex installation from an account without collaborator access after the
  repository is public.
- Obtain an independent Claude Code review and record its findings. Completed: Claude Code confirmed
  the history metadata and missing license findings and found no regression in the audit changes.
  The result is recorded in
  [issue #71](https://github.com/foxyberry/agent-harness/issues/71#issuecomment-5200286253).
