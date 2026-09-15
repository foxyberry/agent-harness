---
name: skill-command-examples
description: Put a required SKILL.md argument in the command example people copy and paste, not in a footnote
type: feedback
---

If an argument is required in a skill's instructions, do not explain it only in a footnote
("always pass X") — put it **in the fenced command example itself**. Agents and users copy and
paste the main example; they do not apply the footnote.

**Why:** in the first fix for issue #3, `--project-dir` was documented only in a PATH_NOTE
footnote, so the rendered command example was missing the argument. The Codex review flagged it
as a P2: "copy and paste and it is still missing — the bug survives."

**How to apply:** when the example differs per adapter, as with build.sh, render the argument
inside the example through a placeholder (for example `{{PROJECT_DIR_ARG}}`) and leave it empty
for the adapters that do not need it. Footnotes are only for explaining why or what to replace it
with. Related: [[adapter-cross-project-testing]], [[build-drift]].
