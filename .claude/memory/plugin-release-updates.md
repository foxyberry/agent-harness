---
name: plugin-release-updates
description: For user-facing plugin delivery, bump the Claude and Codex manifest versions together and manage the update instructions as one release unit — including "close your Codex sessions first"
type: project
---

When shipping agent-harness to users, keep local dogfooding separate from user-facing releases.
Both adapters leave an install cache behind, so a user-facing change bumps the version in
`plugins/codex/.codex-plugin/plugin.json` **and** `plugins/harness/.claude-plugin/plugin.json`
**together**, keeping the two equal, and the README's update commands are kept current alongside
them.

**Why:** shipping forever as the same version makes it hard for users to tell whether they are on
the latest build, and it forces you to keep walking them through internal steps like remove/add
to refresh the cache. Never ask users to refresh a cache while leaving the version unchanged. Let
the two manifests drift and "which version am I on?" has two different answers depending on which
tool asks. Ordinary users should not be updating often — they should update only at stable
release boundaries.

**How to apply:** a user-facing change ships with both version bumps, and the README keeps only
the short install/update commands. Codex currently has no `plugin update`, so the update path is
`codex plugin marketplace upgrade foxyberry` followed by
`codex plugin remove/add agent-harness@foxyberry`.

**The update instructions must also say "close your Codex sessions first."** When Codex installs a
new version it deletes the old version's cache folder, and a session that is still running keeps
pointing at the deleted path, which breaks its shell commands (restarting fixes it; nothing is
lost). Claude keeps old versions, so this does not apply there. Since 0.8.1 the hooks absorb this
themselves, but a session started on an earlier version is still affected — see
`docs/codex-hooks.md`.

Do local verification by dogfooding with `./build.sh` and a local marketplace, but do not present
that procedure as the way ordinary users update.

**Measured (2026-07-12):** even in a dev install (where the marketplace points straight at the
repo), the VERSION shown by `codex plugin list` stays at the snapshot taken at install time —
skill content is live, but the version string stayed `0.1.0` until a remove/add. That is the
measured basis for "bump the version + tell people to remove/add".
