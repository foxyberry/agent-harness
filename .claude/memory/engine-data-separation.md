---
name: engine-data-separation
description: core/hooks is a generic engine; "what to do" is project data (.claude/memory/*.json). No hardcoding
type: project
---

Coupling in the hooks is **relocated, not removed**. core/hooks is a tool- and
project-independent engine, and the specifics — "which file → which memory" (routes.json),
"which pattern → which warning" (reflection-rules.json) — are decided by the project's
`.claude/memory/*.json` data.

**Why:** hardcoding (for example `.kt → code-quality.md`) into core fits exactly one project and
breaks reuse. The engine/data split is what the harness's three-layer structure ("data = the
project") actually means.

**How to apply:** do not put language- or project-specific logic (extensions, filenames, language
rules) in core/hooks. When a new match or rule is needed, the engine should only "read a config
file and apply it", and the actual values live in project-template (as examples) or in each
project's `.claude/memory/`. Related: [[hooks-live-dir-gotcha]]
