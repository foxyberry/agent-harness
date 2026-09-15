#!/usr/bin/env python3
"""Portable work handoff.

Keeps the "portable handoff state" that lets work be picked up across sessions,
tools, machines and people, in a file that is committed to git.

Why it is needed:
  - A transcript (.jsonl) is local and tool-specific. Claude=`~/.claude/projects/...`,
    Codex=`~/.codex/sessions/...` differ in location and format, and both live outside
    the repo, so another machine/person/tool cannot read them.
    (see: cross-machine-feedback-placement)
  - This handoff file, on the other hand, is committed at `.claude/handoff/<branch>.md`,
    so every machine/person/agent that clones or pulls sees exactly the same thing.

Layers:
  - Portable path (first choice) = this handoff file → **once committed**, for anyone,
    anywhere, on any tool.
  - Deep recovery (supplement)   = the local transcript (.jsonl) → same machine, same
    tool only.

  ⚠️ This script does not commit (saving ≠ committing, tracked/staged ≠ committed). The
  commit state is never baked into the body; `handoff_sync_state()` computes it at
  lookup time (#133).

Subcommands:
  save  Collects current git facts automatically and creates/updates the handoff file.
        The narrative (summary/done/next/verification) is filled in by the agent via
        arguments.
  load  Prints the handoff file for the current branch plus current git facts
        (the portable path). If a local transcript exists, adds a "deep recovery
        available" hint.

Tool-agnostic: both Claude (.claude/skills) and Codex (.agents/skills) call this script.
Standard library only (no external dependencies). Python 3.8+.

Usage:
  python3 scripts/handoff/handoff.py save \
      --agent claude --summary "..." --done "..." --next "..." --verify "..."
  python3 scripts/handoff/handoff.py load
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HANDOFF_DIR = ".claude/handoff"
AUTO_MARK = "<!-- handoff:auto -->"
SNIP = 500


def run(cmd, cwd=None):
    """Run a shell command and return (stdout, ok). Never raises; empty string on failure."""
    try:
        out = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=20
        )
        return out.stdout.strip(), out.returncode == 0
    except Exception:
        return "", False


def probe(cmd, cwd=None):
    """Run a command for state detection — returns `(returncode, ran)`.

    `run()` folds the returncode into a bool, which cannot distinguish "absent (1)"
    from "the lookup itself failed (128)". `ran=False` means "unknown", not "no".
    """
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=20)
        return out.returncode, True
    except Exception:
        return None, False


def head_blob(root, rel):
    """The **raw bytes** of `<rel>` as stored in the HEAD commit. None if unavailable
    ("unknown")."""
    try:
        out = subprocess.run(["git", "cat-file", "blob", "HEAD:" + rel],
                             cwd=root, capture_output=True, timeout=20)
    except Exception:
        return None
    return out.stdout if out.returncode == 0 else None


def repo_root(explicit=None):
    """Project root used to save/look up the handoff. Priority order:
    1) Explicit argument (--project-dir) — fixed regardless of cwd. Needed when the script
       runs from a skill folder (as Codex does) to name the user project explicitly
       (the skill folder is a plugin cache and may live outside the repo).
    2) CLAUDE_PROJECT_DIR env — set by Claude hooks/plugins.
    3) git toplevel (relative to cwd) — when cwd is inside the user project.
    4) cwd fallback.
    If the explicit/env path is a git repo (or below one), it is normalized to the toplevel."""
    cand = explicit or os.environ.get("CLAUDE_PROJECT_DIR")
    if cand:
        cand = os.path.abspath(os.path.expanduser(cand))
        out, ok = run(["git", "rev-parse", "--show-toplevel"], cwd=cand)
        return out if ok and out else cand
    out, ok = run(["git", "rev-parse", "--show-toplevel"])
    return out if ok and out else os.getcwd()


def current_branch(root):
    out, ok = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    return out if ok and out else "DETACHED"


def safe_name(branch):
    """Branch name → file name: replace path characters such as '/' with '-'."""
    return branch.replace("/", "-").replace(" ", "_")


def handoff_path(root, branch):
    return os.path.join(root, HANDOFF_DIR, safe_name(branch) + ".md")


# Baking the state into the file body inevitably makes it false on one side of the commit
# (#133), so the state is computed every time save/load runs. `committed-*` is judged
# against the local commit — push state is never claimed.
HANDOFF_STATE_LABELS = {
    "missing": "no file",
    "unknown": "cannot tell — git lookup failed (no claim either way about the commit state)",
    "untracked": "not committed — not even added to git (untracked)",
    "staged-new": "not committed — only staged with `git add`",
    "committed-clean": "committed — the current file matches the HEAD commit contents (local commit only; pushed state is separate)",
    "committed-modified": "modified after commit — the current file (working tree) differs from the HEAD commit contents",
    "committed-untracked": "HEAD holds a committed copy, but the current file is outside git tracking (`git rm --cached` etc.)",
}


def handoff_sync_state(root, path):
    """Commit state of this one handoff file. Index membership → HEAD membership →
    **content comparison**, in that order.

    tracked ≠ committed ≠ identical content — a mere `git add` makes it tracked, and
    saving again after a commit splits HEAD from the working tree. Three rules:

    - Read the exit code as-is. Flattening it with `!= 0` disguises a failed lookup (128)
      as absence (1) (non-repository → unknown; repository with zero commits → cannot
      possibly be committed).
    - Compare contents by pulling the HEAD blob and diffing **bytes**, not via `git diff`.
      diff quietly reports "no difference" under `assume-unchanged`/`skip-worktree`, which
      makes us call content that is not in HEAD "committed". Byte comparison errs in the
      opposite direction — line endings or filters may make a clean file look modified,
      but it can never call content that is missing from HEAD clean.
    - Push state is not judged, and nothing is said about index state beyond this file.
    """
    if not os.path.isfile(path):
        return "missing"
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    if rel.startswith("../"):
        return "unknown"

    idx_code, idx_ran = probe(["git", "ls-files", "--error-unmatch", "--", rel], cwd=root)
    if not idx_ran or idx_code not in (0, 1):
        return "unknown"
    in_index = idx_code == 0

    head_code, head_ran = probe(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD:" + rel], cwd=root
    )
    if not head_ran or head_code not in (0, 1):
        return "unknown"
    if head_code == 1:
        return "staged-new" if in_index else "untracked"
    if not in_index:
        return "committed-untracked"

    committed = head_blob(root, rel)
    if committed is None:
        return "unknown"
    try:
        with open(path, "rb") as f:
            current = f.read()
    except OSError:
        return "unknown"
    return "committed-clean" if committed == current else "committed-modified"


def handoff_state_label(state):
    return HANDOFF_STATE_LABELS.get(state, HANDOFF_STATE_LABELS["unknown"])


def now_iso():
    # ISO timestamp including the local timezone (e.g. 2026-06-30T14:05:00+09:00)
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def machine_name():
    """Return an explicit machine label without leaking the host name by default."""
    return os.environ.get("HARNESS_HANDOFF_MACHINE", "undisclosed")


def git_facts(root):
    """Collect git facts so the receiving side can cross-check the current state even
    without a transcript."""
    branch = current_branch(root)
    status, _ = run(["git", "status", "-sb"], cwd=root)
    stat_unstaged, _ = run(["git", "diff", "--stat"], cwd=root)
    stat_staged, _ = run(["git", "diff", "--cached", "--stat"], cwd=root)
    # Commits ahead of origin/main (the base may not be main, but this is the most common
    # reference point)
    ahead, ahead_ok = run(
        ["git", "log", "--oneline", "origin/main..HEAD"], cwd=root
    )
    # Open PRs (when gh exists and the network is up). Ignored on failure.
    pr, pr_ok = run(
        ["gh", "pr", "list", "--head", branch,
         "--json", "number,title,url",
         "--jq", '.[] | "#\\(.number) \\(.title) — \\(.url)"'],
        cwd=root,
    )
    return {
        "branch": branch,
        "status": status,
        "stat_unstaged": stat_unstaged,
        "stat_staged": stat_staged,
        "ahead": ahead if ahead_ok else "(cannot compare against origin/main — fetch needed)",
        "pr": pr if (pr_ok and pr) else "(none, or lookup failed)",
    }


def transcript_hint(root):
    """Return a "deep recovery available" hint when a local transcript **for this project**
    exists on this machine.

    ⚠️ Both branches must be scoped to the project. An older Codex branch scanned all of
    `~/.codex/sessions` and only reported "they exist", which never told you which session
    belonged to this project. That sent people and models off to dig through logs by hand,
    and hand-digging has no scoping — so a globally newest session **from someone else's
    project** was mistaken for the most recent work (issue #95). The point of the hint is
    not to count anything but to name **the next command to run** — if there is nothing,
    say so plainly.
    """
    hints = []
    # Claude: ~/.claude/projects/<cwd '/'→'-'>/*.jsonl — the directory itself is per project,
    # so a single listdir yields both the scoping and the count (cheap).
    claude_dir = _claude_project_dir(root)
    if os.path.isdir(claude_dir):
        jsonls = [f for f in os.listdir(claude_dir) if f.endswith(".jsonl")]
        if jsonls:
            hints.append(
                f"{len(jsonls)} Claude transcript(s) @ {claude_dir} "
                f"→ deep recovery via `/fw --from claude` or `/fw-both` (this machine only)"
            )
    # Codex: the project marker lives inside the file (session_meta.cwd), so counting would
    # mean opening every one of them. The hint needs **the next command**, not a count, so
    # this stops at "does one exist".
    if _has_project_codex_rollout(root):
        hints.append(
            f"Codex rollout present @ {_codex_sessions_dir()} "
            f"→ deep recovery via `/fw --from codex` or `/fw-both` (this machine only)"
        )
    return hints


def _claude_project_dir(root):
    """Claude Code project transcript dir for this repo, if present."""
    proj_key = _claude_project_key(root)
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", proj_key)


def _claude_project_key(path):
    """Claude Code project dir key. Current Claude Code replaces path separators and dots."""
    return path.replace("/", "-").replace(".", "-")


def _recent_claude_transcripts(root, limit=2, exclude_stem=None):
    """Most recent top-level Claude Code transcripts. Subagent logs are auxiliary and are
    excluded by default.
    exclude_stem: skip the file whose name stem (= session UUID) equals this — so that
    `fw both` does not mistake the currently running Claude session (the one that invoked
    fw) for the most recent work."""
    claude_dir = _claude_project_dir(root)
    if not os.path.isdir(claude_dir):
        return []
    rows = []
    try:
        for fn in os.listdir(claude_dir):
            if not fn.endswith(".jsonl"):
                continue
            if exclude_stem and os.path.splitext(fn)[0] == exclude_stem:
                continue
            fp = os.path.join(claude_dir, fn)
            try:
                rows.append((os.path.getmtime(fp), os.path.getsize(fp), fp))
            except OSError:
                continue
    except OSError:
        return []
    rows.sort(reverse=True)
    return rows[:limit]


TIMELINE_CAP = 20


def _ts_label(ts):
    """ISO timestamp → `MM-DD HH:MM` (local). Falls back to the leading substring if parsing
    fails.

    Why the date is included: a single session commonly spans several days (across reboots,
    or on resume). With only hours and minutes the order looks inverted.
    """
    if not isinstance(ts, str) or not ts:
        return "--:--"
    try:
        return (datetime.fromisoformat(ts.replace("Z", "+00:00"))
                .astimezone().strftime("%m-%d %H:%M"))
    except ValueError:
        return ts[:16]


def _push_timeline(summary, ts, kind, text):
    """Append one row to the chronological timeline (only the last TIMELINE_CAP are kept).

    `last_users`/`last_assistants`/`last_tools` are truncated per kind, so they **never
    interleave**. But "what happened last" is all about order — which tool ran after which
    instruction — and that shape cannot show it (issue #96).
    """
    if not text:
        return
    summary.setdefault("timeline", []).append((_ts_label(ts), kind, text))
    summary["timeline"] = summary["timeline"][-TIMELINE_CAP:]


def _timeline_lines(summary, header="- Timeline (chronological, most recent last):"):
    rows = summary.get("timeline") or []
    if not rows:
        return []
    out = [header, "```"]
    out.extend(f"[{ts}] {kind:<6} {text}" for ts, kind, text in rows)
    out.append("```")
    return out


def _clip(text, n=SNIP):
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= n else text[: n - 1] + "…"


def _content_text(content):
    """Extract only the human-readable text from Claude message content (str|list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _content_text(content.get("content") or content.get("text") or "")
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            if isinstance(block, str):
                parts.append(block)
            continue
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "tool_result":
            parts.append(_content_text(block.get("content", "")))
    return "\n".join(str(p) for p in parts if p)


def _user_speech_text(content):
    """Extract **only what the human typed** from a user message.

    `role: "user"` in Claude JSONL carries two more things besides human speech: tool
    results (`tool_result`) and the `<system-reminder>` blocks the harness injects. Without
    filtering them out, "recent user input" and the chronological timeline get buried under
    tool output, and **who asked for what disappears** (issue #96).

    ⚠️ A single message frequently carries tool_result and text **together** (a
    system-reminder follows the tool result). Deciding by "is everything a tool_result?"
    misses that case — so instead of filtering by block kind, this **collects only human
    speech**.

    `_content_text` does read tool_result bodies, because task-notification extraction needs
    that. That use stays as is; only the speech decision happens here.
    """
    if isinstance(content, str):
        return _strip_reminders(content)
    if not isinstance(content, list):
        return ""
    parts = [
        b.get("text", "") for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    ]
    return _strip_reminders("\n".join(p for p in parts if p))


def _strip_reminders(text):
    return re.sub(r"<system-reminder>.*?</system-reminder>", "", text or "", flags=re.S).strip()


def _task_notes(text):
    notes = []
    for m in re.finditer(r"<task-notification>(.*?)</task-notification>", text or "", re.S):
        body = m.group(1)
        note = {}
        for key in ("task-id", "status", "summary", "output-file"):
            km = re.search(rf"<{key}>(.*?)</{key}>", body, re.S)
            if km:
                note[key] = km.group(1).strip()
        if note:
            notes.append(note)
    return notes


def _summarize_claude_transcript(path):
    """Summarize only the last signals from a Claude Code JSONL that matter for pickup."""
    summary = {
        "last_prompt": "",
        "last_users": [],
        "last_assistants": [],
        "last_tools": [],
        "task_notes": [],
        "pr_links": [],
        "rate_limit": "",
    }
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    data = json.loads(line)
                except Exception:
                    continue

                typ = data.get("type")
                if typ == "last-prompt" and data.get("lastPrompt"):
                    summary["last_prompt"] = data.get("lastPrompt", "")

                if typ == "pr-link":
                    summary["pr_links"].append(
                        f"#{data.get('prNumber')} {data.get('prUrl')}"
                    )

                content = data.get("content")
                if isinstance(content, str):
                    for note in _task_notes(content):
                        summary["task_notes"].append(note)

                msg = data.get("message")
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                blocks = msg.get("content")

                if role == "user":
                    text = _content_text(blocks)
                    if "<local-command-caveat>" in text:
                        continue
                    for note in _task_notes(text):
                        summary["task_notes"].append(note)
                    # Speech detection looks only at what the human typed (tool results and
                    # system-reminders excluded). Task-notification extraction already ran
                    # above against `text` (the full content).
                    speech = _user_speech_text(blocks)
                    if speech and "<task-notification>" not in speech:
                        summary["last_users"].append(_clip(speech))
                        summary["last_users"] = summary["last_users"][-3:]
                        _push_timeline(summary, data.get("timestamp"), "USER", _clip(speech, 160))

                elif role == "assistant":
                    if isinstance(blocks, list):
                        for block in blocks:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "text":
                                txt = _clip(block.get("text", ""))
                                if txt:
                                    summary["last_assistants"].append(txt)
                                    summary["last_assistants"] = summary["last_assistants"][-3:]
                                    _push_timeline(summary, data.get("timestamp"),
                                                   "AGENT", _clip(txt, 160))
                            elif block.get("type") == "tool_use":
                                name = block.get("name", "")
                                inp = block.get("input", {}) or {}
                                cmd = inp.get("command") or inp.get("file_path") or ""
                                summary["last_tools"].append(_clip(f"{name}: {cmd}", 240))
                                summary["last_tools"] = summary["last_tools"][-5:]
                                _push_timeline(summary, data.get("timestamp"),
                                               "TOOL", _clip(f"{name}: {cmd}", 160))

                local = data.get("content") if data.get("subtype") == "local_command" else ""
                if isinstance(local, str) and "session limit" in local:
                    summary["rate_limit"] = _clip(local)
    except OSError:
        pass
    return summary


def _format_claude_deep_recovery(root, limit=2, transcript=None, exclude_stem=None):
    paths = []
    if transcript:
        paths = [(0, 0, os.path.expanduser(transcript))]
    else:
        paths = _recent_claude_transcripts(root, limit=limit, exclude_stem=exclude_stem)
    if not paths:
        return []

    out = ["## 🧩 Claude JSONL quick recovery (this machine only)"]
    for mt, size, path in paths:
        if not os.path.exists(path):
            out.append(f"- missing: `{path}`")
            continue
        label = os.path.basename(path)
        when = datetime.fromtimestamp(os.path.getmtime(path)).astimezone().isoformat(timespec="seconds")
        out.append(f"### `{label}`")
        out.append(f"- Path: `{path}`")
        out.append(f"- Updated: {when} · Size: {os.path.getsize(path)} bytes")
        s = _summarize_claude_transcript(path)
        if s["last_prompt"]:
            out.append(f"- Last prompt: {_clip(s['last_prompt'], 300)}")
        out.extend(_timeline_lines(s))
        if s["last_users"]:
            out.append("- Recent user input:")
            for item in s["last_users"]:
                out.append(f"  - {item}")
        if s["last_assistants"]:
            out.append("- Recent assistant replies:")
            for item in s["last_assistants"]:
                out.append(f"  - {item}")
        if s["last_tools"]:
            out.append("- Recent tool calls:")
            for item in s["last_tools"]:
                out.append(f"  - `{item}`")
        if s["task_notes"]:
            out.append("- Background task notifications:")
            task_notes = []
            seen_tasks = set()
            for note in s["task_notes"]:
                key = (note.get("task-id"), note.get("output-file"), note.get("summary"))
                if key in seen_tasks:
                    continue
                seen_tasks.add(key)
                task_notes.append(note)
            for note in task_notes[-5:]:
                summary = note.get("summary", "(no summary)")
                status = note.get("status", "?")
                task_id = note.get("task-id", "?")
                out.append(f"  - {task_id} [{status}] {summary}")
                if note.get("output-file"):
                    out.append(f"    output: `{note['output-file']}`")
        if s["pr_links"]:
            out.append("- PR links:")
            for link in list(dict.fromkeys(s["pr_links"]))[-3:]:
                out.append(f"  - {link}")
        if s["rate_limit"]:
            out.append(f"- Session limit signal: {s['rate_limit']}")
    return out


# ---------- Codex rollout detection/summary (for fw) ----------

def _codex_sessions_dir():
    return os.path.join(os.path.expanduser("~"), ".codex", "sessions")


def _codex_rollout_meta(path):
    """First line session_meta of a rollout → (session_id, cwd). Otherwise (None, None)."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.loads(f.readline())
        if d.get("type") == "session_meta":
            p = d.get("payload") or {}
            return p.get("id"), p.get("cwd")
    except Exception:
        pass
    return None, None


def _project_matcher(root):
    """A callable deciding whether a `cwd` belongs to this project.

    build.sh co-locates repo_identity in the same directory as this script. If it is absent
    (the script was copied on its own), this falls back to the old path-prefix check — that
    misses worktrees, but it does not die."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from repo_identity import ProjectMatcher
    except ImportError:
        return lambda cwd: cwd == root or bool(cwd and cwd.startswith(root + os.sep))
    m = ProjectMatcher(root)
    # Record the worktrees that are alive right now. Auto reflection (HARNESS_AUTO_REFLECT)
    # is **off by default**, so leaving the bookkeeping to it alone would mean the cache
    # never gets written — and then fw/history cannot find a session after its worktree is
    # deleted. Record here too, so users who never enabled reflection can still look back.
    m.record_worktrees()
    return m.belongs


def _recent_codex_rollouts(root, limit=2, days=30, exclude_sid=None):
    """Recent Codex rollouts of this project (session_meta.cwd == root or below it) as
    [(mtime, size, path)]. Regardless of the start-date directory, metadata is read only for
    files whose mtime falls within the last `days` (so resumed old sessions are not missed).
    exclude_sid: skip the rollout whose session_meta.id equals this — so that `fw both` does
    not mistake the currently running Codex session (the one that invoked fw) for the most
    recent work."""
    base = _codex_sessions_dir()
    if not os.path.isdir(base):
        return []
    today = datetime.now()
    cutoff = today.timestamp() - (days * 86400)
    matcher = _project_matcher(root)
    rows = []
    for directory, _dirs, names in os.walk(base):
        for fn in names:
            if not (fn.startswith("rollout-") and fn.endswith(".jsonl")):
                continue
            fp = os.path.join(directory, fn)
            try:
                mtime = os.path.getmtime(fp)
                size = os.path.getsize(fp)
            except OSError:
                continue
            if mtime < cutoff:
                continue
            sid, cwd = _codex_rollout_meta(fp)
            # Decided by git repository identity rather than path prefix — that catches
            # worktrees living outside the project folder (`~/.codex/worktrees/`, a sibling
            # `.agent-worktrees/`).
            if not matcher(cwd):
                continue
            if exclude_sid and sid == exclude_sid:
                continue
            rows.append((mtime, size, fp))
    rows.sort(reverse=True)
    return rows[:limit]


def _has_project_codex_rollout(root, days=30):
    """Is there any Codex rollout for this project — stops at the first match.

    Counting via `_recent_codex_rollouts` would open the metadata of every rollout and ask
    for the git identity of each cwd (1200+ files on this machine = several hundred ms).
    That cost is worth it for a `--deep` summary, but there is no reason to pay it on
    **every ordinary `load`** for one hint line.

    So this (1) starts from the newest file and (2) stops at the first match — when a match
    exists, usually only a few files are read. Only the "nothing found" case scans
    everything, and that scan is not skipped: claiming "present" prematurely sends the user
    off to dig by hand, and hand-digging has no project scoping (issue #95).
    """
    base = _codex_sessions_dir()
    if not os.path.isdir(base):
        return False
    cutoff = datetime.now().timestamp() - (days * 86400)
    cands = []
    for directory, _dirs, names in os.walk(base):
        for fn in names:
            if not (fn.startswith("rollout-") and fn.endswith(".jsonl")):
                continue
            fp = os.path.join(directory, fn)
            try:
                mtime = os.path.getmtime(fp)
            except OSError:
                continue
            if mtime >= cutoff:
                cands.append((mtime, fp))
    if not cands:
        return False
    cands.sort(reverse=True)  # newest first — a session of mine is usually near the front
    matcher = _project_matcher(root)
    for _mtime, fp in cands:
        if matcher(_codex_rollout_meta(fp)[1]):
            return True
    return False


def _summarize_codex_rollout(path):
    """Summarize only the pickup signals (recent user/assistant text, tool names) from a
    Codex rollout JSONL."""
    summary = {"last_users": [], "last_assistants": [], "last_tools": []}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "response_item":
                    continue
                p = d.get("payload") or {}
                pt = p.get("type")
                if pt == "message":
                    role = p.get("role")
                    texts = [
                        b.get("text", "")
                        for b in (p.get("content") or [])
                        if isinstance(b, dict)
                        and b.get("type") in ("input_text", "output_text", "text")
                        and (b.get("text") or "").strip()
                    ]
                    if not texts:
                        continue
                    joined = _clip("\n".join(texts))
                    if role == "user":
                        summary["last_users"].append(joined)
                        summary["last_users"] = summary["last_users"][-3:]
                        _push_timeline(summary, d.get("timestamp"), "USER", _clip(joined, 160))
                    elif role == "assistant":
                        summary["last_assistants"].append(joined)
                        summary["last_assistants"] = summary["last_assistants"][-3:]
                        _push_timeline(summary, d.get("timestamp"), "AGENT", _clip(joined, 160))
                elif pt == "function_call":
                    name = p.get("name", "")
                    if name:
                        summary["last_tools"].append(_clip(name, 120))
                        summary["last_tools"] = summary["last_tools"][-5:]
                        _push_timeline(summary, d.get("timestamp"), "TOOL", _clip(name, 160))
    except OSError:
        pass
    return summary


def _format_codex_deep_recovery(root, limit=1, session=None, exclude_sid=None):
    if session:
        paths = [(0, 0, os.path.expanduser(session))]
    else:
        paths = _recent_codex_rollouts(root, limit=limit, exclude_sid=exclude_sid)
    if not paths:
        return ["## 🧩 Codex rollout: no recent session log for this project (this machine only)"]
    out = ["## 🧩 Codex rollout quick recovery (this machine only)"]
    for _mt, _size, path in paths:
        if not os.path.exists(path):
            out.append(f"- missing: `{path}`")
            continue
        when = datetime.fromtimestamp(os.path.getmtime(path)).astimezone().isoformat(timespec="seconds")
        out.append(f"### `{os.path.basename(path)}`")
        out.append(f"- Path: `{path}`")
        out.append(f"- Updated: {when} · Size: {os.path.getsize(path)} bytes")
        s = _summarize_codex_rollout(path)
        out.extend(_timeline_lines(s))
        if s["last_users"]:
            out.append("- Recent user input:")
            for item in s["last_users"]:
                out.append(f"  - {item}")
        if s["last_assistants"]:
            out.append("- Recent assistant replies:")
            for item in s["last_assistants"]:
                out.append(f"  - {item}")
        if s["last_tools"]:
            out.append("- Recent tool calls:")
            for item in s["last_tools"]:
                out.append(f"  - `{item}`")
    return out


def _parse_since(value):
    match = re.fullmatch(r"(\d+)([mhdw])", value or "")
    if not match:
        raise ValueError("--since format: 30m, 12h, 7d, 2w")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError("--since must be 1 or greater")
    units = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    seconds = amount * units[match.group(2)]
    if seconds > 3650 * 86400:
        raise ValueError("--since allows at most 10 years")
    return seconds


def _contains_keyword(path, keyword):
    if not keyword:
        return True
    needle = keyword.casefold()
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return any(needle in line.casefold() for line in handle)
    except OSError:
        return False


def _history_rows(root, from_tool="both", limit=20, since="30d", grep=None, no_content=False):
    cutoff = datetime.now().timestamp() - _parse_since(since)
    candidates = []
    if from_tool in ("claude", "both"):
        for mtime, size, path in _recent_claude_transcripts(root, limit=10000):
            if mtime >= cutoff:
                candidates.append(("claude", mtime, size, path))
    if from_tool in ("codex", "both"):
        days = max(1, int(_parse_since(since) / 86400) + 1)
        for mtime, size, path in _recent_codex_rollouts(root, limit=10000, days=days):
            if mtime >= cutoff:
                candidates.append(("codex", mtime, size, path))
    candidates.sort(key=lambda item: item[1], reverse=True)
    if grep:
        candidates = candidates[:200]

    rows = []
    for tool, mtime, size, path in candidates:
        if grep and not _contains_keyword(path, grep):
            continue
        if no_content:
            snippet = ""
            if tool == "claude":
                project_match = "Claude project directory key"
            else:
                _sid, cwd = _codex_rollout_meta(path)
                project_match = "exact cwd" if cwd == root else "nested cwd"
        elif tool == "claude":
            summary = _summarize_claude_transcript(path)
            snippet = summary["last_prompt"]
            project_match = "Claude project directory key"
        else:
            _sid, cwd = _codex_rollout_meta(path)
            summary = _summarize_codex_rollout(path)
            snippet = summary["last_users"][-1] if summary["last_users"] else ""
            project_match = "exact cwd" if cwd == root else "nested cwd"
        if "\ufffd" in snippet:
            snippet = ""
        rows.append({
            "time": datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds"),
            "tool": tool,
            "path": path,
            "size": size,
            "project_match": project_match,
            "snippet": _clip(snippet, 160),
            "resume_command": _history_resume_command(root, path),
        })
        if len(rows) >= limit:
            break
    return rows


def _history_resume_command(root, path):
    return " ".join([
        shlex.quote(sys.executable),
        shlex.quote(os.path.abspath(__file__)),
        "fw",
        "--session",
        shlex.quote(path),
        "--project-dir",
        shlex.quote(root),
    ])


def _render_history(root, rows, no_content=False):
    if not rows:
        # "Nothing found" is exactly when the project being inspected must be named —
        # pointing at the wrong target and genuinely having no logs look identical here.
        return (
            "# Session history\n\n"
            f"- Project: `{root}`\n\n"
            "No Claude/Codex session log matches these conditions."
        )
    lines = [
        "# Session history (read-only)",
        "",
        f"- Project: `{root}`",
        f"- Results: {len(rows)}",
    ]
    for index, row in enumerate(rows, 1):
        lines.extend([
            "",
            f"## {index}. {row['time']} · {row['tool']}",
            f"- Log path: `{row['path']}`",
            f"- Project match: {row['project_match']} · {row['size']} bytes",
        ])
        if not no_content:
            lines.append(f"- Last user input: {row['snippet'] or '(no parsable input)'}")
        lines.append(f"- Resume with: `{row['resume_command']}`")
    return "\n".join(lines)


def cmd_history(args):
    root = repo_root(getattr(args, "project_dir", None))
    if args.limit <= 0:
        print("ERROR: --limit must be 1 or greater.", file=sys.stderr)
        return 2
    try:
        rows = _history_rows(
            root,
            from_tool=args.from_tool,
            limit=args.limit,
            since=args.since,
            grep=args.grep,
            no_content=args.no_content,
        )
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"project": root, "rows": rows}, ensure_ascii=False, indent=2))
    else:
        print(_render_history(root, rows, no_content=args.no_content))
    return 0


def _target_lines(root, explicit):
    """State up front **which project this run looked at** and **why it picked that one**.

    A pickup that points at the wrong target still looks perfectly fine — that repo's
    branch and sessions come out normally. The tool did what it was told, so that alone is
    not a defect; the defect is **having no way to notice it was wrong**. One line so the
    reader can check it against the project they meant (issue #95: "show the detected
    cwd/git root and the reason it was chosen").
    """
    if explicit:
        why = "`--project-dir` argument"
    elif os.environ.get("CLAUDE_PROJECT_DIR"):
        why = "`CLAUDE_PROJECT_DIR` environment variable"
    else:
        why = "current directory"
    return [f"- Target project: `{root}` (chosen via: {why})", ""]


def _facts_lines(facts, header):
    """git_facts dict → human-readable markdown lines (shared by load and fw)."""
    return [
        header,
        f"- Branch: `{facts['branch']}`",
        "- Commits ahead of origin/main:", "```", facts["ahead"] or "(none)", "```",
        "- Changed files (status -sb):", "```", facts["status"] or "(none)", "```",
        f"- Open PRs: {facts['pr']}",
    ]
def cmd_save(args):
    root = repo_root(getattr(args, "project_dir", None))
    branch = current_branch(root)
    if branch in ("DETACHED", "HEAD"):
        print("⚠️  DETACHED HEAD — check out a branch first.", file=sys.stderr)
        return 1
    facts = git_facts(root)

    done = args.done or "(not written)"
    nxt = args.next or "(not written)"
    summary = args.summary or "(not written)"
    verify = args.verify or "(not written)"

    body = f"""# Work handoff — {branch}

> Updated: {now_iso()} · Agent: {args.agent} · Machine: {machine_name()}
> ⚠️ This file is the **handoff source of truth** for picking work up — it has to be
> committed and pushed to reach another machine/person/tool.
> Check **git, not this body**, for whether the file is committed right now (a state
> written down at save time goes stale the moment you commit — `load` recomputes the
> state at lookup time and tells you).
> Whoever picks this up should read it first and **cross-check it against the current
> git state** before proceeding.
> Do not trust the transcript alone — git facts win.

## Summary
{summary}

## Done
{done}

## Remaining / next actions
{nxt}

## Verification status
{verify}

---
{AUTO_MARK}
## Git facts (collected automatically @ {now_iso()})

- Branch: `{facts['branch']}`
- Commits ahead of origin/main:
```
{facts['ahead'] or '(none)'}
```
- Changed files (status -sb):
```
{facts['status'] or '(none)'}
```
- diff --stat (unstaged):
```
{facts['stat_unstaged'] or '(none)'}
```
- diff --stat (staged):
```
{facts['stat_staged'] or '(none)'}
```
- Open PRs: {facts['pr']}
"""

    target = handoff_path(root, branch)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(body)
    rel = os.path.relpath(target, root).replace(os.sep, "/")
    print(f"✅ Handoff saved: {rel}")
    print(f"   Current git state: {handoff_state_label(handoff_sync_state(root, target))}")
    # The wording has to stay true in every state — it must not contradict the state line
    # right above it when that line already says `committed`.
    print("   → Commit and push to deliver it to another machine/person/tool:")
    # `-C <root>` is always included. With `--project-dir` or a skill-folder run, cwd is not
    # the target repository, so guiding only `git add <rel>` would run in the wrong repo.
    # Absolute paths go to stdout only — putting them in the committed body would pollute
    # the portable source of truth, since they differ per machine.
    at = f"git -C {shlex.quote(root)}"
    print(f"      {at} add -- {shlex.quote(rel)}")
    print(f"      {at} commit    # follow the project rules for commit messages and approval")
    print("   (The push command depends on your remote/upstream setup, so it is not "
          "suggested here — do it the project's way.)")
    return 0


def cmd_load(args):
    root = repo_root(getattr(args, "project_dir", None))
    branch = current_branch(root)
    target = handoff_path(root, branch)
    out = []
    out.append(f"# Picking up work — branch `{branch}`")
    out.append("")
    out.extend(_target_lines(root, getattr(args, "project_dir", None)))
    rel = os.path.relpath(target, root).replace(os.sep, "/")
    state = handoff_sync_state(root, target)
    if state != "missing":
        # The state goes **above** the body. Files written by older versions still carry a
        # baked-in "this file is committed" banner, so the reader has to see the real state
        # before running into that sentence (#133).
        out.append(f"## 📄 Handoff file ({rel})")
        out.append("")
        out.append(f"- git state: {handoff_state_label(state)}")
        # Only the provenance is stated. Whether it matches HEAD is what the state line
        # above says — asserting "this is not HEAD" here would contradict that line in the
        # committed-clean case.
        out.append("- The body below is **the working-tree file as read from disk** (not "
                   "extracted from HEAD).")
        out.append("")
        with open(target, encoding="utf-8") as f:
            out.append(f.read().rstrip())
    else:
        out.append("## 📄 Handoff file: none")
        out.append(f"   (this branch has no `{rel}` yet)")
    out.append("")
    out.append("---")
    out.extend(_facts_lines(git_facts(root), "## 🔎 Current git facts (cross-check against the handoff)"))
    out.append("")
    hints = transcript_hint(root)
    if hints:
        out.append("## 🧩 Deep recovery (this machine only)")
        for h in hints:
            out.append(f"- {h}")
    else:
        # Writing "proceed from the committed handoff only" would assert, in the same
        # output, that the very file reported as `not committed` above is committed (#133).
        # What this points at is the channel, not the commit state.
        out.append("## 🧩 Deep recovery: no local transcript on this machine — proceed from the saved handoff file only")
    if args.deep or args.transcript:
        out.append("")
        out.extend(_format_claude_deep_recovery(root, transcript=args.transcript))
        # ⚠️ The Codex side must always be emitted too. It used to summarize only Claude and
        # leave Codex to a one-line hint, which meant deep had no answer when picking up
        # Codex work and sent people and models to dig through logs by hand — hand-digging
        # has no project scoping, so someone else's project session was mistaken for the
        # most recent work (issue #95). When `--transcript` names a specific file, that
        # means "look only at this one", so this is skipped.
        if not args.transcript:
            out.append("")
            out.extend(_format_codex_deep_recovery(root))
    print("\n".join(out))
    return 0


def _live_session_excludes(root, current):
    """Compute the identifiers that exclude the current tool's live session (the very
    session that invoked this fw). The opposite tool is not running, so it is not excluded
    (its newest log really is the most recent work).
    Returns: (claude_exclude_stem, codex_exclude_sid) — None where not applicable.

    Rule: **exclude only when the live session is positively identified among this
    project's logs.** The id an env var points at is returned only when it matches an
    actual project log; when it does not match, return None (hide nothing).
    - claude: env `CLAUDE_CODE_SESSION_ID` (= transcript file stem) matches one of this
      project's transcripts.
    - codex : env `CODEX_THREAD_ID` (presumed: rollout session_meta.id) or
      `CODEX_SESSION_ID` matches one of this project's rollouts.

    Why "hide nothing" on a mismatch (i.e. no fallback that excludes the newest): when we
    cannot confirm what the env var points at (e.g. Codex exporting a CODEX_THREAD_ID that
    differs from the rollout id), blindly excluding the newest log hides it in exactly the
    case where that newest log is the **most recent work** to restore (the worse failure).
    Not hiding costs, at worst, one extra line in the list for my own live session, and
    pickup is safe because current git wins anyway."""
    claude_stem = codex_sid = None
    cur = (current or "").lower()
    if cur == "claude":
        env_stem = os.environ.get("CLAUDE_CODE_SESSION_ID")
        if env_stem:
            rows = _recent_claude_transcripts(root, limit=50)
            stems = {os.path.splitext(os.path.basename(r[2]))[0] for r in rows}
            if env_stem in stems:
                claude_stem = env_stem
    elif cur == "codex":
        # Current Codex exports CODEX_THREAD_ID (presumed: session_meta.id); CODEX_SESSION_ID
        # is the secondary candidate. Both are checked against the project's rollout ids —
        # `A or B` would short-circuit when A is truthy but does not match, never looking at
        # B, and would miss the live session in environments where B is the right one.
        candidates = [c for c in (os.environ.get("CODEX_THREAD_ID"),
                                  os.environ.get("CODEX_SESSION_ID")) if c]
        if candidates:
            rows = _recent_codex_rollouts(root, limit=50)
            ids = {_codex_rollout_meta(r[2])[0] for r in rows}
            for c in candidates:
                if c in ids:
                    codex_sid = c
                    break
    return claude_stem, codex_sid


def cmd_fw(args):
    """Restore work automatically from session logs (Claude .jsonl / Codex rollout) — tool
    switch pickup. Unlike handoff-load it restores from logs without an explicit save (the
    supplementary path). git facts win.

    Source selection: --session (explicit) > --from (tool) > auto (newest of both).
    Rendered skills pass the **opposite tool** as the --from default (Claude→codex,
    Codex→claude) — structurally preventing the accident of picking the current session,
    whose log is the newest one."""
    root = repo_root(getattr(args, "project_dir", None))
    src = (args.from_tool or "auto").lower()
    limit = max(1, int(getattr(args, "limit", 1) or 1))

    out = [
        f"# Tool switch pickup (fw) — source: {src}",
        "",
        *_target_lines(root, getattr(args, "project_dir", None)),
        "> ⚠️ fw is the supplementary path that restores automatically from **unsaved session"
        " logs**. If a committed handoff (`load`) exists, that is the source of truth, and"
        " **the current git state always wins over the logs**.",
        "",
    ]

    # Live-session exclusion applies to **every source**. It used to be computed and used
    # only in the `both` branch, so looking for the previous session of the same tool with
    # `--from claude` found the newest = this very session and summarized itself
    # (issue #96). `--session` is the only exception — naming a file explicitly means "look
    # at this one", so it is not excluded.
    claude_stem, codex_sid = _live_session_excludes(root, getattr(args, "current", None))

    if args.session:
        # Format auto-detection: a first line of session_meta means a Codex rollout,
        # otherwise a Claude .jsonl.
        sid, _cwd = _codex_rollout_meta(args.session)
        if sid:
            out.extend(_format_codex_deep_recovery(root, session=args.session))
        else:
            out.extend(_format_claude_deep_recovery(root, transcript=args.session))
    elif src == "codex":
        out.extend(_format_codex_deep_recovery(root, limit=limit, exclude_sid=codex_sid))
    elif src == "claude":
        out.extend(_format_claude_deep_recovery(root, limit=limit, exclude_stem=claude_stem))
    elif src == "both":  # both logs at once — only the current tool's live session excluded
        out.extend(_format_codex_deep_recovery(root, limit=limit, exclude_sid=codex_sid))
        out.append("")
        out.extend(_format_claude_deep_recovery(root, limit=limit, exclude_stem=claude_stem))
    else:  # auto — the single newest session across both tools
        # Two per tool. The exclusion has to be applied **before** sorting, and taking only
        # one would leave the candidate list empty when that one is the live session,
        # falling through to "no logs" — failing to find a perfectly good log from the
        # opposite tool.
        cand = [("claude",) + r for r in
                _recent_claude_transcripts(root, limit=2, exclude_stem=claude_stem)]
        cand += [("codex",) + r for r in
                 _recent_codex_rollouts(root, limit=2, exclude_sid=codex_sid)]
        cand.sort(key=lambda t: t[1], reverse=True)  # t[1]=mtime
        if not cand:
            out.append("## 🧩 No recent session log for this project (neither Claude nor Codex, this machine only)")
        elif cand[0][0] == "codex":
            out.extend(_format_codex_deep_recovery(root, session=cand[0][3]))
        else:
            out.extend(_format_claude_deep_recovery(root, transcript=cand[0][3]))

    out.append("")
    out.append("---")
    out.extend(_facts_lines(git_facts(root), "## 🔎 Current git facts (cross-check against the logs — git wins)"))
    print("\n".join(out))
    return 0


def main():
    p = argparse.ArgumentParser(description="Work handoff (save/load/fw/history)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("save", help="Save the current work state to a handoff file")
    s.add_argument("--agent", default=os.environ.get("HANDOFF_AGENT", "unknown"),
                   help="Authoring agent (claude|codex|person-name). Defaults to env HANDOFF_AGENT")
    s.add_argument("--summary", help="One or two line work summary")
    s.add_argument("--done", help="What is done (markdown bullets allowed)")
    s.add_argument("--next", dest="next", help="Remaining work / next actions (markdown bullets allowed)")
    s.add_argument("--verify", help="Verification status (test/build/review results)")
    s.add_argument("--project-dir", dest="project_dir",
                   help="Absolute path of the user project root to save the handoff in. If "
                        "omitted: CLAUDE_PROJECT_DIR env → git root of cwd. Must be given "
                        "explicitly when running from a skill folder (plugin cache).")
    s.set_defaults(func=cmd_save)

    l = sub.add_parser("load", help="Print the current branch's handoff plus git facts")
    l.add_argument("--deep", action="store_true",
                   help="Also print pickup clues by briefly summarizing recent Claude Code "
                        "JSONL from the same machine")
    l.add_argument("--transcript",
                   help="Summarize a Claude Code JSONL at an explicitly given path (a full "
                        "path is recommended over a session UUID)")
    l.add_argument("--project-dir", dest="project_dir",
                   help="Absolute path of the user project root to look the handoff up in. "
                        "If omitted: CLAUDE_PROJECT_DIR env → git root of cwd. Must be given "
                        "explicitly when running from a skill folder (plugin cache).")
    l.set_defaults(func=cmd_load)

    fw = sub.add_parser("fw", help="Restore work automatically from session logs — tool switch pickup (even without a save)")
    fw.add_argument("--from", dest="from_tool", default="auto",
                    choices=["claude", "codex", "auto", "both"],
                    help="Source tool to restore from. Rendered skills default to the "
                         "opposite tool (Claude→codex, Codex→claude). If the session broke "
                         "within the same tool (reboot, context exhaustion), name that tool "
                         "directly — the live session is excluded via --current, so it will "
                         "not pick itself. auto=the single newest of both. both=both logs "
                         "together.")
    fw.add_argument("--current", choices=["claude", "codex"],
                    help="The tool running fw right now. Its live session (the one just "
                         "started) is excluded **for every --from value** so it is not "
                         "mistaken for the most recent work. Rendered skills pass this "
                         "automatically.")
    fw.add_argument("--session",
                    help="Path to a specific session log (Claude .jsonl or Codex rollout). "
                         "The format is detected automatically.")
    fw.add_argument("--limit", type=int, default=1, help="Number of recent sessions to summarize (default 1)")
    fw.add_argument("--project-dir", dest="project_dir",
                    help="Absolute path of the project root. If omitted: CLAUDE_PROJECT_DIR "
                         "env → git root of cwd. Must be given explicitly when running from "
                         "a skill folder (plugin cache).")
    fw.set_defaults(func=cmd_fw)

    history = sub.add_parser("history", help="Read-only listing/search of Claude and Codex session logs")
    history.add_argument("--from", dest="from_tool", default="both",
                         choices=["claude", "codex", "both"],
                         help="Tool to list (default both)")
    history.add_argument("--limit", type=int, default=20, help="Maximum number of results (default 20)")
    history.add_argument("--since", default="30d", help="Lookback window: 30m, 12h, 7d, 2w (default 30d)")
    history.add_argument("--grep", help="Case-insensitive keyword search across the whole candidate JSONL")
    history.add_argument("--no-content", action="store_true",
                         help="Hide prompt snippets and print only paths and metadata")
    history.add_argument("--json", action="store_true", help="JSON output")
    history.add_argument("--project-dir", dest="project_dir",
                         help="Absolute path of the project root. Required when running from a plugin cache.")
    history.set_defaults(func=cmd_history)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
