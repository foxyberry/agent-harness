#!/usr/bin/env python3
"""
SessionStart hook: surfaces the project's shared memory index (.claude/memory/INDEX.md) early in
the session.

The goal is not to push the full memory bodies in, but to make sure the agent does not miss
"which shared memories exist". The detailed rules themselves are injected by the existing
memory-search hook, matched to the file being edited.

Configuration (optional): $CLAUDE_PROJECT_DIR/.claude/memory/index-load.json
  {
    "enabled": true,
    "max_chars": 12000
  }

Defaults are enabled=true, max_chars=12000. No-op when .claude/memory/INDEX.md is absent.
Passes silently on any exception (fail-open).
"""
import json
import os
import sys

# hook_io is a **required dependency** that build.sh co-locates in the same directory as this hook.
# The canonical project_dir resolution lives there too, so continuing to run via a local fallback on
# a broken install with the file missing would let the contract diverge per hook again. Only when
# running directly from the core source tree do we look at ../scripts.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(1, os.path.join(os.path.dirname(_HERE), "scripts"))
from hook_io import project_dir as _project_dir, trace_entry  # noqa: E402

DEFAULT_MAX_CHARS = 12000
MAX_CAP = 50000


def _safe_child_path(parent, name):
    """Return parent/name only when it stays inside parent.

    INDEX.md is auto-injected at SessionStart, so this blocks the path escape where an untrusted repo
    symlinks a local file outside .claude/memory into the model's context.
    """
    if os.path.sep in name or (os.path.altsep and os.path.altsep in name):
        return None
    base = os.path.realpath(parent)
    full = os.path.realpath(os.path.join(parent, name))
    if full == base or full.startswith(base + os.sep):
        return full
    return None


def _safe_memory_dir(project_dir):
    """Allow only a .claude/memory that lives inside the project.

    A memory directory symlinked to a location outside the project is excluded from auto-injection.
    """
    project = os.path.realpath(project_dir)
    memory = os.path.realpath(os.path.join(project_dir, ".claude/memory"))
    if memory == project or memory.startswith(project + os.sep):
        return memory
    return None


def _load_config(memory_dir):
    cfg = {"enabled": True, "max_chars": DEFAULT_MAX_CHARS}
    path = _safe_child_path(memory_dir, "index-load.json")
    if not path:
        return cfg
    if not os.path.exists(path):
        return cfg
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return cfg
        if isinstance(data.get("enabled"), bool):
            cfg["enabled"] = data["enabled"]
        if isinstance(data.get("max_chars"), int):
            cfg["max_chars"] = min(max(data["max_chars"], 1000), MAX_CAP)
    except Exception:
        return cfg
    return cfg


def _read_index(index_path, max_chars):
    try:
        with open(index_path, encoding="utf-8") as f:
            text = f.read(max_chars + 1).strip()
    except Exception:
        return None
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars].rstrip()
        + f"\n\n[truncated: .claude/memory/INDEX.md exceeds {max_chars} chars]"
    )


def main():
    if os.environ.get("REFLECT_JOB") == "1":
        sys.exit(0)

    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    event = data.get("hook_event_name") or data.get("hookEventName")
    trace_entry(__file__, event)
    if event != "SessionStart":
        sys.exit(0)

    project_dir = _project_dir(data)
    memory_dir = _safe_memory_dir(project_dir)
    if not memory_dir:
        sys.exit(0)
    index_path = _safe_child_path(memory_dir, "INDEX.md")
    if not index_path:
        sys.exit(0)
    if not os.path.exists(index_path):
        sys.exit(0)

    cfg = _load_config(memory_dir)
    if not cfg["enabled"]:
        sys.exit(0)

    index = _read_index(index_path, cfg["max_chars"])
    if not index:
        sys.exit(0)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "## Project Shared Memory Index\n"
                "The project has committed shared memory at `.claude/memory/`. "
                "Use this index to discover relevant rules and decisions; read the "
                "referenced memory files when they are relevant to the current task.\n\n"
                f"[memory/INDEX.md]\n{index}"
            ),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
