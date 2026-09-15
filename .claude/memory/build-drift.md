---
name: build-drift
description: core/ is the source of truth and the adapters are generated. After editing core, always run ./build.sh and commit the generated output in the same commit
type: project
---

`core/` is the single source of truth; `plugins/harness/` and `plugins/codex/` are **generated
output** produced by build.sh. If you changed core, run `./build.sh` and put the regenerated
adapters in the **same commit**.

**Why:** CI (`.github/workflows/validate.yml`) runs build.sh and then checks for drift with
`git diff` — committing without running the build fails as "core and adapter out of sync".
Editing an adapter by hand gets overwritten by the next build.

**How to apply:** do not edit the adapters (plugins/harness, plugins/codex) directly — fix it in
core and run build.sh. Write SKILL.md with placeholders such as `{{RULES_FILE}}` and let the
build.sh render step substitute the per-adapter value. Bundled scripts must be referenced from
inside the adapter only through `${CLAUDE_PLUGIN_ROOT}` (Claude); no `../`.
