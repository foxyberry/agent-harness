---
name: code-quality
description: code quality rules for this project (example — replace with your own)
type: feedback
---

<This is an example file. The `*.kt` rule in routes.json injects it — replace the content with your project's rules.>

- No Kotlin `!!` — use `requireNotNull` or `?: return`.
- For accumulating collections, prefer `fold`/`associate`/`sumOf` over `var` plus a loop.

**Why:** NPEs kept hiding until runtime.
**How to apply:** read this memory when it is injected before an edit, and do not ignore reflection hook warnings.
