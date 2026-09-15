---
name: committed-artifact-env-leak
description: Never auto-populate environment details into committed artifacts (handoff, memory). The default is `undisclosed`; a label requires an environment-variable opt-in
type: project
---

Artifacts the harness produces that are **committed to git** must not be auto-populated with
execution environment details (hostname, absolute paths, username). The default is that nothing
is disclosed, and only a team that wants a label turns one on explicitly through an environment
variable.

**Why:** `handoff.py` called `socket.gethostname()` unconditionally and stamped the real machine
name into the handoff header. That was a convenience while it stayed local, but a handoff exists
to be committed and shared, so when the repository went public (#71/#72) a personal machine name
was about to be published with it. A convenience feature became a leak path by riding the
sharing route — and it was only caught in the audit just before going public.

**How to apply:**
- In code that generates a committed artifact, do not auto-insert `socket.gethostname()`, the
  absolute path from `os.getcwd()`, or an expanded `~` into headers or metadata.
- If you need one, record **only a non-sensitive label the user supplied**, such as
  `HARNESS_HANDOFF_MACHINE` (default `undisclosed`).
- Pin both the default and the opt-in with regression tests — the danger is the default silently
  reverting.
- When adding a new artifact format, ask "does this get committed?" first; if it does, leave the
  environment fields out.

Related: [[engine-data-separation]], [[adapter-cross-project-testing]]
