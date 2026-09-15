---
name: hooks-live-dir-gotcha
description: When the plugin root is a live working copy, hook edits hit other running sessions at once. Deleting a hook script used to block every Bash call in them; build.sh now guards against that, but sessions started on an unguarded version are still at risk
type: project
---

`${CLAUDE_PLUGIN_ROOT}` does not always mean the same thing. In a **live-dir dev install** it
points straight at a working copy — for example `<path-to-agent-harness>/plugins/harness` — so
edits there are live for every session immediately. In an ordinary install it points at a
versioned cache copy instead, and nothing you edit in the repo reaches it until the next install
or update. Check which one you have before reasoning about blast radius; do not assume every dev
setup is a live directory.

Two things follow when the plugin root *is* a live working copy. First, editing or deleting a
file under `plugins/harness/hooks/` takes effect at the next hook firing in **every session
running in every other project**. Second, `plugins/harness/hooks/` and `plugins/codex/hooks/` are
**generated** from `core/hooks/` — a change in core reaches those sessions only after `./build.sh`.

**Why:** a session loads hooks.json into memory at start. If the script a registered command
points at disappears, an already running session executes a missing file under the old
configuration. Unguarded, `python3` exits 2, Claude Code reads a PreToolUse exit 2 as "blocked",
and **every Bash call in that session is blocked.** This happened twice: on 2026-07-07 in
ket-woojin, by deleting pre-push-guard, and again on the Codex side, where installing a new
version deletes the old version's cache folder out from under a running session. In both cases
the error names the hook script, so the symptom does not point at the cause.

**What is fixed now:** `hook_command()` in `build.sh` generates every registered command in the
guarded form

```sh
p="${CLAUDE_PLUGIN_ROOT}/hooks/<script>"; if [ -f "$p" ]; then python3 "$p"; fi
```

A missing script exits 0 and blocks nothing, while a hook that **deliberately** exits 2 still
blocks — the `if` form passes exit 1 and 2 through untouched, which is why it is written this way
rather than as `python3 "$p" || exit 0` (that form would silently disarm a real block).
`tests/test_hook_wiring.py` enforces it by running the registered command strings in a shell and
checking that a missing script does not produce exit 2. Since 0.8.1 the hooks absorb this class
of failure themselves; see `docs/codex-hooks.md` for the measured cache behavior on each tool.

**How to apply:** before deleting or renaming a core/hooks hook, (1) confirm whether the affected
sessions are running a guarded build — sessions started on a version from before the guard
shipped can still be blocked by a missing script, and they are the only ones that need the
warning; (2) if an immediate unblock is needed there, leave an exit-0 no-op shim in its place;
and (3) explain that an affected session must be restarted to load the current hooks.json, since
the in-memory copy never reloads. A guard in the command string is the only available protection:
a hook script cannot fail open on its own **absence** — the interpreter dies before it ever opens
the file. Related: [[engine-data-separation]]
