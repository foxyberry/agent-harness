# Public release audit

Audit date: 2026-08-06

Tracking issue: [#71](https://github.com/foxyberry/agent-harness/issues/71)

## Current decision

**PUBLIC AND VERIFIED**. Git history is preserved with its existing identity metadata, the
repository uses the MIT License, and the final repository and GitHub surface scans found no secret
or credential exposure.

## Checks completed

- `./build.sh` completed without core/adapter drift.
- `python3 -m unittest discover -s tests` passed all 85 tests after audit changes.
- Common token, private-key, credential, absolute-path, and local-home patterns were scanned in the
  current tree and Git patch history. No credential or private-key match was found.
- Tracked handoff files, repository URLs, author identities, open pull requests, branches, recent
  Actions runs, and release metadata were reviewed.
- Recent Actions runs pass, PR #72 is the only open pull request, and there are no published
  releases.
- Gitleaks 8.30.1 scanned every Git ref with `--log-opts=--all` and found no leaks. A separate
  working-tree scan covers final files that are not yet committed.
- Issue and pull request bodies, issue comments, review comments, and the 10 most recent Actions logs
  were checked for credential and local-identity patterns. One local path in merged PR #42 was
  replaced with `<repo>`; the repeated scan found no remaining match outside the accepted Git
  identity metadata.

The targeted pattern scan and dedicated Gitleaks scans of all Git refs and the working tree both
completed.

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

- Repository visibility changed to public after PR #72 merged.
- GitHub private vulnerability reporting is enabled.
- README, `docs/overview.html`, and `AGENTS.md` use the public `foxyberry/agent-harness` Codex address.
- The agent-harness plugin version `0.4.11` installed through Codex from the public address in an
  empty `CODEX_HOME` with Git credentials disabled.
- The same agent-harness plugin version installed through Claude Code in an empty
  `CLAUDE_CONFIG_DIR`; with SSH forced to fail, Claude automatically retried the public repository
  over anonymous HTTPS and completed installation.
- Commands and observed results are recorded in
  [issue #71](https://github.com/foxyberry/agent-harness/issues/71#issuecomment-5200842740).
- Issue #71 remains open until this documentation update is merged and verified on `main`.
- Obtain an independent Claude Code review and record its findings. Completed: Claude Code confirmed
  the history metadata and missing license findings and found no regression in the audit changes.
  The result is recorded in
  [issue #71](https://github.com/foxyberry/agent-harness/issues/71#issuecomment-5200286253).
