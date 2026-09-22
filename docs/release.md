# Releases

This file records what each user-facing release contains and how a release is prepared.
The short install and update commands stay in the [README](../README.md); this page carries
the release notes and the surrounding procedure.

## How a release is prepared

1. Bump the version in `plugins/harness/.claude-plugin/plugin.json` and
   `plugins/codex/.codex-plugin/plugin.json` **together**, keeping the two equal. CI fails if
   they drift.
2. Update the `Plugin version` line in both READMEs and add the release notes here.
3. Run `./build.sh`, the test suite, and manifest checks; review the release diff.
4. Open the version PR, complete cross-review, and merge it into `main`.

The default GitHub marketplace source follows `main`. Merging the version PR makes the new
version available through that source; users still need to refresh the marketplace and update
the plugin. A branch version bump alone does not update existing installations. A source pinned
to another revision follows that configured revision.

Do not push users to update often. Local dogfooding (`./build.sh` plus a local marketplace)
is a development loop, not the way ordinary users update.

## Updating

Run these commands in a terminal. Restart Claude Code after updating its plugin.

```bash
# Claude Code
claude plugin marketplace update foxyberry
claude plugin update agent-harness@foxyberry

# Codex — there is no `plugin update` yet, so refresh the snapshot and re-add
codex plugin marketplace upgrade foxyberry
codex plugin remove agent-harness@foxyberry
codex plugin add agent-harness@foxyberry
```

**Close your Codex sessions first.** Codex deletes the old version's cache directory when it
installs a new one, and a session that is already running keeps pointing at the deleted path.
Restarting clears it; nothing is lost. From 0.8.1 onward the hooks absorb this themselves, so the
warning applies to sessions started on an earlier version. Claude Code keeps its old version
directories, so its sessions survive an update. Details in [codex-hooks.md](codex-hooks.md).

**Updating the plugin does not touch your project's files.** The plugin ships the shared
machinery only. Your `AGENTS.md`, `CLAUDE.md`, `.github/`, and `.claude/memory/` are never
overwritten by an update. When `project-template/` changes in a release, those changes reach an
existing project **only if you merge them in by hand** — read the diff and adopt what applies.
`/template-check` lists the `.claude/memory/` template files a project lacks or has with different
content; it is read-only.

---

## 0.14.0

Contains [#152](https://github.com/foxyberry/agent-harness/pull/152) and
[#155](https://github.com/foxyberry/agent-harness/pull/155). Both adapters still ship **8 skills**.

### Retrospective skip markers survive a long commit subject ([#152](https://github.com/foxyberry/agent-harness/pull/152))

`gh pr view` cuts a long commit subject mid-character and moves the rest into the body, so
`[skip reflect]` arrived as `[ski…` / `…p reflect]` and never matched: the merged PR kept being
asked for a retrospective ([#148](https://github.com/foxyberry/agent-harness/issues/148)). When a
headline comes back truncated, the hook now fetches the full messages once from the REST commits
endpoint and uses them only for commits it can match by SHA. If that call fails the truncated form
is kept, so the marker can still be missed — no worse than before, and no new failure mode. The
pre-existing limit is unchanged: only a PR's first 100 commits are examined.

### `/memory-update` captures decisions from the session ([#155](https://github.com/foxyberry/agent-harness/pull/155))

Candidate extraction collected `feedback`, `project` and `reference` only, so a session that made
a decision produced no ADR candidate. The only writers of ADR drafts were the opt-in retrospective
job and the manual mining CLI, which is why the schema shipped in 0.12.x and nothing was ever
promoted ([#153](https://github.com/foxyberry/agent-harness/issues/153)).

`/memory-update` now extracts `decision` candidates from the session and routes them to its
promotion step, and `/feedback-review` hands a decision over instead of storing it as a rule — a
rule has no `chain` and no `id`, so it cannot be superseded later.

Every alternative listed in a promoted ADR must come from something that was actually said, with
its source named in Evidence. If nothing was rejected, the candidate does not become an ADR. This
is a real failure, not a precaution: a mined draft listed two alternatives that appear in no
source, because the gate requires the section and the model filled it in.

---

## 0.13.0

Contains [#146](https://github.com/foxyberry/agent-harness/pull/146),
[#149](https://github.com/foxyberry/agent-harness/pull/149), and
[#150](https://github.com/foxyberry/agent-harness/pull/150). Both adapters now ship **8 skills**.

### New skill: `/template-check` ([#146](https://github.com/foxyberry/agent-harness/pull/146))

The plugins now ship a read-only reference copy of `project-template/.claude/memory/`.
`/template-check` compares your project's `.claude/memory/` with it and reports missing,
different, identical, and skipped files. It **never writes**: nothing is copied or overwritten, and your
project configuration stays yours. A differing file may be a deliberate customization — no record
of the template version you copied exists, so the check cannot tell the two apart.

### Retrospective skip rules: adoption stays per project ([#149](https://github.com/foxyberry/agent-harness/pull/149))

This repository adopted a `.claude/memory/reflect-skip.json` whose only rule is `ignore_paths`
for the root `.gitignore`. That file belongs to **this repository only**. The update does not
write it, or any other skip configuration, into your project. A project that copied the template
before `reflect-skip.json` existed keeps the engine defaults until someone adds the file by hand.
[self-improvement-hooks.md](self-improvement-hooks.md#adopting-the-skip-rules-in-an-existing-project)
gives the manual recipe, starting with `/template-check`.

### Commit skip markers count only as directives ([#150](https://github.com/foxyberry/agent-harness/pull/150))

`[skip reflect]`, `skip-reflect`, and `no-reflect` used to match anywhere in a commit message, so a
commit that only *explained* a marker skipped its own retrospective. A marker now counts only in
two places:

- **the subject line**, unless that exact occurrence is wrapped in backticks, which is ignored
  as a quotation; or
- **a body line that contains only the marker**, outside fenced code blocks.

Other mentions in the body are ignored, including prose, backticked or `> ` quoted lines, and
fenced examples. Label matching and `paths`/`ignore_paths` behave as before.

The same rule applies to custom `commit_messages` patterns in your `reflect-skip.json`. If a
project relied on its pattern matching in the middle of body text, it now gets **more**
retrospectives, never fewer. To keep skipping those PRs, put the pattern in the subject. Putting it
on its own body line also works, unless the pattern was stored with surrounding spaces. Details:
[Where a commit marker counts](self-improvement-hooks.md#where-a-commit-marker-counts).

### Unchanged in this release

- **Project files.** An update still never overwrites `AGENTS.md`, `CLAUDE.md`, `.github/`, or
  `.claude/memory/`; `project-template/` changes are merged by hand.
- **Privacy and human approval.** Drafted lessons still go through
  `_pending → human approval → committed`, and the automatic retrospective stays off until you set
  `HARNESS_AUTO_REFLECT=1`.
- **Codex hook scope.** `pr-merge-reflect` remains registered on Codex for merge detection and
  shared queue updates only. The UserPromptSubmit reminder and the automatic LLM retrospective stay
  unregistered there ([#85](https://github.com/foxyberry/agent-harness/issues/85)).
- **Update commands.** Close your Codex sessions before updating. For Claude Code, run
  `claude plugin marketplace update foxyberry`, then `claude plugin update agent-harness@foxyberry`,
  then restart Claude Code. See [Updating](#updating).

---

## 0.12.2

Contains [#140](https://github.com/foxyberry/agent-harness/pull/140)–[#144](https://github.com/foxyberry/agent-harness/pull/144).

### Handoff reports the real Git state ([#141](https://github.com/foxyberry/agent-harness/pull/141))

Saving and loading a handoff no longer assert a commit state that the file cannot know.

- `handoff-save` writes a local file and **does not commit or push it**. It prints the file's
  current Git state and the exact `git -C <project root> add`/`commit` commands to run, and the
  saved text deliberately records no commit state, because that claim goes stale the moment the
  file is committed. Saved is not committed, and the skill now says so.
- `handoff-load` reports the file's current Git state, including whether it matches `HEAD` or
  has changed since being committed. It also identifies uncommitted or untracked files and
  cases where the state cannot be determined. A committed result means a
  **local commit only** — push state is not checked, so confirm that separately before treating
  a handoff as available on another machine.
- Handoff files written by earlier versions still load with their bodies intact; the old baked-in
  banner no longer wins over the measured state.

This closes the mislabeling in [#133](https://github.com/foxyberry/agent-harness/issues/133).
Loading still does not retire a consumed handoff
([#138](https://github.com/foxyberry/agent-harness/issues/138) remains open).

### Memory skills anchor to the target project ([#143](https://github.com/foxyberry/agent-harness/pull/143))

`memory-update` and `feedback-review` resolve an explicit project root before changing
directories. On Codex the skill's own directory sits in a plugin cache outside your repository,
so the previous rendering could aim project-file paths at the cache instead of the project.
Project paths are now written out literally and passed through explicitly.

### English runtime text, Korean input still understood ([#142](https://github.com/foxyberry/agent-harness/pull/142))

Hook and script output, comments, and in-code documentation are English. Korean handling is kept
where it matches **input rather than output**: Korean merge announcements typed by users still
trigger the merge hooks, and existing Korean `_rejected.md` ledgers and Korean handoff bodies are
still supported.

### English documentation and project template ([#140](https://github.com/foxyberry/agent-harness/pull/140), [#144](https://github.com/foxyberry/agent-harness/pull/144))

The remaining documentation, the `project-template/` guidance, and the PR templates are English.
English is the primary text; a Korean version is optional and goes below it as a supplement.
`README.ko.md` remains the Korean translation of the README.

The `project-template/` changes in this release **must be merged by hand** into a project that
already adopted an earlier template. Nothing is overwritten for you, and `AGENTS.md`,
`CLAUDE.md`, and `.github/` are the files most likely to collide with rules you already have.

### Unchanged in this release

- **Privacy and human approval.** Automatically drafted lessons still go through
  `_pending → human approval → committed`. The automatic retrospective spawns `claude -p` and
  stays off until you set `HARNESS_AUTO_REFLECT=1`.
- **Codex hook scope.** `pr-merge-reflect` is registered on Codex for merge detection and shared
  queue updates only. The UserPromptSubmit reminder and the automatic LLM retrospective remain
  unregistered there until an installed-plugin smoke test verifies them
  ([#85](https://github.com/foxyberry/agent-harness/issues/85)).
