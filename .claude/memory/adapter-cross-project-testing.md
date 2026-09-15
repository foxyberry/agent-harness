---
name: adapter-cross-project-testing
description: Verify adapter behavior and public installation with the repo, credentials and caches isolated — the development environment hides the bug
type: project
---

Runtime behavior of the Claude/Codex adapters (handoff save paths and the like) has to be
verified from **a separate project outside the agent-harness repo**. In a dev install the
marketplace points straight at the repo, so the skill folder sits inside the harness repo and
any cwd-based logic (git toplevel lookup and so on) always finds the repo — which **hides
cross-project bugs**.

**Why:** in issue #3 the cwd-dependent bug in handoff.py went unnoticed through all of
dogfooding — it happened to work because the skill folder was inside the repo. It only broke in
a real user install, where the skill lives in the plugin cache, outside the repo.

**How to apply:** when verifying adapter script behavior, create a scratch project with
`git init`, copy the skill scripts to a path outside the repo, and run them against that
scratch project. "It works inside the harness" is not proof.

Isolate marketplace install and update checks so they do not reuse an existing installation or
your GitHub credentials.

- Codex: run marketplace add/install/upgrade with an empty `CODEX_HOME` and an empty `GIT_CONFIG_GLOBAL`
- Claude Code: use an empty `CLAUDE_CONFIG_DIR` and an empty `GIT_CONFIG_GLOBAL`
- To verify an anonymous public install, force SSH to fail with `GIT_SSH_COMMAND=/usr/bin/false` and confirm the HTTPS fallback
- Do not stop at the success message — check the source URL, the plugin version, the enabled state and the install cache

**Why:** during the public-release issue #71, this machine's SSH credentials and an existing
plugin cache could have masked what an external user actually gets. Only after forcing empty
configuration and failed authentication was the public HTTPS install proven independently.

Related: [[skill-command-examples]], [[build-drift]].
