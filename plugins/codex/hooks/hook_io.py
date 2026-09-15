#!/usr/bin/env python3
"""Shared **input normalization** and **output emission** for the edit hooks (Claude + Codex).

Inputs arrive in a different shape per tool (see below), and each tool may read a
different output key (`emit_context`). If every hook handled both on its own, we would
eventually fix only one side — so it all lives here.

## Input normalization

The edit hooks (memory-search, reflection) only need two things: **which file was
edited** and **what was added**. The shape carrying that information differs per tool.

| Tool | tool_name | Where it lives |
|---|---|---|
| Claude | `Edit` | `tool_input.file_path` + `new_string` |
| Claude | `Write` | `tool_input.file_path` + `content` |
| Claude | `MultiEdit` | `tool_input.file_path` + `edits[*].new_string` |
| Codex | `apply_patch` | `tool_input.command` holds the **raw patch text** |

Codex's `command` is the apply_patch text itself, not a JS wrapper (measured on 0.145.0):

    *** Begin Patch
    *** Add File: /tmp/x/test.txt
    +world
    *** End Patch

**A single edit can touch several files** — one Codex patch may carry three `Add File`
markers. That is why this module always returns a **list**; hooks apply their rules per
file.

Any exception degrades to an empty list (fail-open) — a normalization failure must never
block an edit.
"""
import json
import os
import re
import sys

# `*** Add File: path` / `*** Update File: path` / `*** Delete File: path` / `*** Move to: path`
_FILE_MARKER = re.compile(r"^\*\*\*\s+(Add|Update|Delete)\s+File:\s*(.+?)\s*$")
_MOVE_MARKER = re.compile(r"^\*\*\*\s+Move\s+to:\s*(.+?)\s*$")


def project_dir(data=None):
    """Resolve the user project directory the hook is running against, in a tool-common order.

    Claude supplies an environment variable; Codex supplies `cwd` in the input payload.
    The process cwd is only correct when the host runs the hook inside the project, so it
    is the last fallback.
    """
    from_env = os.environ.get("CLAUDE_PROJECT_DIR")
    if from_env:
        return from_env
    if isinstance(data, dict):
        from_payload = data.get("cwd")
        if isinstance(from_payload, str) and from_payload:
            return from_payload
    return os.getcwd()


class EditedFile:
    """One edited file. `path` may be empty (an edit whose path could not be recovered)."""

    __slots__ = ("path", "added")

    def __init__(self, path="", added=""):
        self.path = path or ""
        self.added = added or ""

    def __repr__(self):  # for test failure messages
        return f"EditedFile(path={self.path!r}, added={self.added[:40]!r})"

    def __eq__(self, other):
        return (isinstance(other, EditedFile)
                and self.path == other.path and self.added == other.added)


def edited_files(data):
    """Hook input (stdin JSON dict) → [EditedFile]. Empty list when it is not an edit.

    Does not branch on tool_name — names differ per tool and new ones appear. Decide by
    **shape** instead: `file_path` means a Claude-style edit, a patch in `command` means
    Codex.
    """
    try:
        ti = (data or {}).get("tool_input") or {}
        if not isinstance(ti, dict):
            return []

        file_path = ti.get("file_path")
        if isinstance(file_path, str) and file_path:
            return [EditedFile(file_path, _claude_added(ti))]

        # When the name says shell, it is not an edit even if it looks like a patch —
        # parsing `gh pr create --body "...*** Begin Patch..."` as an edit would route to
        # files that do not exist. shell_command() documents the opposite direction.
        if _is_named(data, "Bash"):
            return []

        command = ti.get("command")
        if isinstance(command, str) and "*** Begin Patch" in command:
            return parse_apply_patch(command)

        return []
    except Exception:
        return []


def _claude_added(ti):
    """Edit=new_string, Write=content, MultiEdit=edits[*].new_string (joined)."""
    for key in ("new_string", "content"):
        value = ti.get(key)
        if isinstance(value, str) and value:
            return value
    edits = ti.get("edits")
    if isinstance(edits, list):
        parts = [
            e.get("new_string", "") for e in edits
            if isinstance(e, dict) and isinstance(e.get("new_string"), str)
        ]
        return "\n".join(p for p in parts if p)
    return ""


def parse_apply_patch(command):
    """Raw apply_patch text → [EditedFile]. Collects only the added lines, per file.

    - When `*** Move to:` follows `*** Update File:`, take the **destination path** —
      that is where the content ends up living.
    - `*** Delete File:` has no added content, but is still listed: memory-search means
      "see this rule when you touch this file", so deletions count too. reflection skips
      entries with no content on its own.
    - Added lines are **selected** by the leading `+` (rather than excluding `-`,
      context, `@@` and `***`). An exclusion list would leak new markers into the content
      as soon as one is introduced.
    """
    files = []
    current = None
    added = []

    def flush():
        if current is not None:
            files.append(EditedFile(current, "\n".join(added)))

    for line in (command or "").splitlines():
        marker = _FILE_MARKER.match(line)
        if marker:
            flush()
            current, added = marker.group(2), []
            continue

        move = _MOVE_MARKER.match(line)
        if move and current is not None:
            current = move.group(1)   # the destination is the final path
            continue

        if line.startswith("***"):    # remaining markers: Begin/End Patch etc.
            continue

        # Strip exactly one `+` and the rest is the added line verbatim.
        # ⚠️ Do not drop `+++` as a unified diff header. apply_patch marks files with
        # `*** ... File:` markers and **never writes** a `+++ b/path` header. Real code,
        # on the other hand, contains lines like `++counter;`, which becomes `+++counter;`
        # in a patch — mistaking it for a header silently drops that code from the checks.
        if current is not None and line.startswith("+"):
            added.append(line[1:])

    flush()
    return files


def _is_named(data, name):
    """Is `tool_name` exactly this? False when the name is absent or different."""
    return ((data or {}).get("tool_name") or "") == name


def shell_command(data):
    """The raw command when this is a shell call, otherwise None.

    Needed once memory-search also fired on `Bash`: some rules must be recalled "when you
    run this command" rather than "when you edit a file" (for example: post the review
    result as a comment before opening a PR). Surfacing those at edit time never reaches
    the moment they are needed (issue #90).

    ⚠️ Edits (`apply_patch`) also arrive in `tool_input.command`, so shape alone cannot
    separate them. Hence: **trust the name where the name is decisive, fall back to shape
    otherwise**:

    1. `tool_name == "apply_patch"` → it is an edit
    2. `tool_name == "Bash"` → it is a shell call. **Still a shell call even when the
       command embeds patch text** — commands quoting a patch really do occur, e.g.
       `gh pr create --body "...*** Begin Patch..."`, and mistaking one for an edit
       silently drops rule injection at exactly that moment (found in Codex review).
    3. Missing or unknown name → decide by the patch marker

    Why this differs from `edited_files`, which does not branch on the name: edit tools
    have many names (`Edit`/`Write`/`MultiEdit`/`apply_patch`) and gain new ones, whereas
    the shell was observed as a single `Bash` on both tools. Use the name only where the
    name is actually decisive.
    """
    try:
        ti = (data or {}).get("tool_input") or {}
        if not isinstance(ti, dict):
            return None
        command = ti.get("command")
        if not isinstance(command, str) or not command:
            return None
        if _is_named(data, "Bash"):
            return command
        if _is_named(data, "apply_patch") or ti.get("file_path"):
            return None
        return command if "*** Begin Patch" not in command else None
    except Exception:
        return None


def added_content(data):
    """All added content of the edit as one string (for callers that ignore file boundaries)."""
    return "\n".join(f.added for f in edited_files(data) if f.added)


def edited_paths(data):
    """Paths of the edited files (for callers that do not need the content)."""
    return [f.path for f in edited_files(data)]


def emit_context(event, text):
    """Write text to inject into the model context to stdout. Empty text emits nothing.

    **Emits the key twice** — nested (`hookSpecificOutput.additionalContext`) and
    top-level (`additionalContext`).

    Claude reads the nested form (verified). The Codex docs list `additionalContext` as
    output for `PreToolUse`/`PostToolUse` but **do not say whether it is nested or
    top-level**. The only event where the nested form was confirmed to work is
    `SessionStart`, and that event also accepts plain stdout, so the nested path was never
    really exercised there.

    Emitting both is correct whichever one is right, and both parsers ignore unknown keys.
    This failure mode is **indistinguishable from success** (the hook exits quietly even
    when nothing was injected), so we do not guess one. Narrow it down once actual
    injection is observed in the target environment.
    """
    if not text:
        return
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": text},
        "additionalContext": text,
    }, ensure_ascii=False))
    sys.stdout.flush()


def trace_entry(script_path, event=None):
    """Append one line recording **that the hook ran**. Only when `HARNESS_HOOK_TRACE` is set.

    Silent failures go unnoticed because "it never ran" and "it ran and had nothing to
    say" look identical from outside. A mismatched matcher that never fires the hook and a
    run that matched no route and injected nothing both show exactly nothing on screen.

    So the line is written **on entry, not on injection**. Putting it in `emit_context`
    would make those two cases identical again and would separate nothing.

    Normally the environment variable is absent and this does nothing. It is turned on
    only for cross-project verification (issue #85, step 4):

        HARNESS_HOOK_TRACE=/tmp/hook-trace.jsonl codex   # or claude

    Any exception is swallowed — a diagnostic that kills the hook defeats its purpose.
    """
    path = os.environ.get("HARNESS_HOOK_TRACE")
    if not path:
        return
    try:
        import time
        record = {
            "hook": os.path.basename(script_path or ""),
            "event": event or "",
            "pid": os.getpid(),
            "ts": time.time(),
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
