#!/usr/bin/env python3
"""
PostToolUse hook (Edit|Write|MultiEdit): injects a short quality warning about the code that was
just written, right next to the tool result. An immediate reminder that "leaving this as-is will
hurt later".

Engine/data separation (the harness's three-layer structure):
- **Engine (core, this file)**: applies regex rules to the newly added code and builds the warnings.
- **Data (project)**: `$CLAUDE_PROJECT_DIR/.claude/memory/reflection-rules.json` defines the
  language/team specific rules (e.g. Kotlin `!!`/`var`). Without it, only the built-in generic rules
  run. Language-specific rules such as Kotlin's do not live in core -- examples are in
  project-template.

Built-in generic rule: warn about leftover TODO/FIXME (every file, language-agnostic). To turn it
off, put `"builtins": {"todo_fixme": false}` in the rules file.

reflection-rules.json format:
  {
    "rules": [
      {"glob": "*.kt", "regex": "!!",
       "message": "`!!` used in {count} place(s) — consider requireNotNull or ?: return"},
      {"glob": "*.kt", "regex": "(?m)^\\s*var ", "min_count": 3,
       "message": "many var declarations ({count}) — consider fold/associate/sumOf"}
    ],
    "packs": [
      {"name": "react-async-timing", "enabled": false, "rules": [...]}
    ]
  }
- glob:  the file this rule applies to (fnmatch; applies to every file when omitted).
- globs: array of globs, used when the rule should apply to any one of several file patterns.
- regex: pattern to look for in the new code (Python re). The number of matches becomes `count`.
- enabled: false disables just this rule.
- min_count: warn only at this many matches or more (default 1).
- message: the warning text. `{count}` is replaced with the match count.
- packs: opt-in rule bundles. Only the rules of packs with enabled=true are applied.

Uses JSON (dependency-free). Passes silently on any exception (fail-open) -- it never blocks the
result of an edit.
"""
import fnmatch
import json
import os
import re
import sys

# build.sh co-locates hook_io in the same directory as this hook (same convention as repo_identity).
# When run directly from the core source tree it lives in ../scripts -- tests load it from there.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(1, os.path.join(os.path.dirname(_HERE), "scripts"))
from hook_io import (  # noqa: E402
    edited_files,
    emit_context,
    project_dir as _project_dir,
    trace_entry,
)

TODO_MESSAGE = "⚠️  TODO/FIXME left behind — remove it once the work is done"


def _load_config(memory_dir):
    path = os.path.join(memory_dir, "reflection-rules.json")
    if not os.path.exists(path):
        return {"rules": [], "builtins": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"rules": [], "builtins": {}}
        rules = data.get("rules", []) if isinstance(data.get("rules"), list) else []
        packs = data.get("packs", []) if isinstance(data.get("packs"), list) else []
        for pack in packs:
            if not isinstance(pack, dict) or pack.get("enabled") is not True:
                continue
            pack_rules = pack.get("rules")
            if isinstance(pack_rules, list):
                rules.extend(pack_rules)
        return {
            "rules": rules,
            "builtins": data.get("builtins", {}) if isinstance(data.get("builtins"), dict) else {},
        }
    except Exception:
        return {"rules": [], "builtins": {}}


def _apply_rule(rule, file_path, content):
    if not isinstance(rule, dict):
        return None
    if rule.get("enabled") is False:
        return None
    if "globs" in rule:
        globs = rule["globs"]
        if isinstance(globs, str):
            patterns = [globs]
        elif isinstance(globs, list):
            patterns = [pattern for pattern in globs if isinstance(pattern, str)]
        else:
            return None
        if not patterns:
            return None
    else:
        if "glob" in rule:
            glob = rule["glob"]
            if not isinstance(glob, str):
                return None
            patterns = [glob]
        else:
            patterns = []
    if patterns and not any(fnmatch.fnmatch(file_path, pattern) for pattern in patterns):
        return None
    regex = rule.get("regex")
    msg = rule.get("message")
    if not regex or not msg:
        return None
    try:
        count = len(re.findall(regex, content))
    except re.error:
        return None
    if count < int(rule.get("min_count", 1)):
        return None
    return "⚠️  " + msg.replace("{count}", str(count))


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    trace_entry(__file__, data.get("hook_event_name"))

    # Only look at files that actually gained content. A single edit can touch several files
    # (a Codex patch), and a deletion has no new code to inspect.
    targets = [f for f in edited_files(data) if f.added]
    if not targets:
        sys.exit(0)

    memory_dir = os.path.join(_project_dir(data), ".claude/memory")
    cfg = _load_config(memory_dir)

    # WARNING: rules are applied **per file**. Merging the added content of several files into one
    # run would let a `{"glob": "*.kt"}` rule see the content of a .md file too. That is why
    # min_count and `{count}` are **per-file** values.
    warnings = []
    for target in targets:
        for warning in _file_warnings(cfg, target.path, target.added):
            if warning not in warnings:   # the same warning repeated across files is shown once
                warnings.append(warning)

    # Plain stdout from PostToolUse never reaches the model. It has to go out as additionalContext
    # to be injected next to the tool result (see hook_io for the key shape).
    if warnings:
        emit_context("PostToolUse", "## Reflection\n" + "\n".join(warnings))
    sys.exit(0)


def _file_warnings(cfg, file_path, content):
    """The list of warnings for a single file."""
    out = []
    # Built-in generic rule: TODO/FIXME (unless turned off)
    if cfg["builtins"].get("todo_fixme", True) and re.search(r"TODO|FIXME", content):
        out.append(TODO_MESSAGE)
    # Project-defined rules
    for rule in cfg["rules"]:
        try:
            warning = _apply_rule(rule, file_path, content)
            if warning:
                out.append(warning)
        except Exception:
            continue
    return out


if __name__ == "__main__":
    main()
