#!/usr/bin/env python3
"""
PR merge retrospection hook -- makes sure a retrospective is not missed when a merge happens. Two
roles:

A) Reminder (the 'pending' queue of un-reflected PRs) -- uses no LLM, always on:
   Detection (queued silently): SessionStart polling (including merges done elsewhere) ·
                                PostToolUse (a merge done here) ·
                                UserPromptSubmit (the user saying "I merged it")
   Delivery: on the next prompt, if anything is pending, inject a "reflect first" instruction and
   clear the queue.

B) Automatic retrospection job (the co-located reflect.py) -- **opt-in, off by default**:
   WARNING: this job spawns a background `claude -p` process. To stop a plugin install alone from
   quietly starting an LLM job on every merge in every project, it is spawned only when the
   environment variable HARNESS_AUTO_REFLECT=1 is set. When enabled: once a merge is confirmed
   within the session, a background job analyses the current session transcript and stores drafts in
   .claude/memory/_pending/. It is detached, so it finishes even if the session is closed.
   At SessionStart, if there are _pending drafts (whoever created them), review is recommended.

Recursion guard: when the job runs with backend=claude, the nested `claude -p` fires this hook
again. If REFLECT_JOB=1 is set, the whole hook no-ops.
gh/network failures and the like all exit 0 silently (they never block the session or the prompt).
Projects without .claude/memory pass through silently too (every data access is fail-open).

Path convention (plugin deployment): the **scripts** (reflect.py, compact_transcript.py) are
co-located in the same directory as this file -> resolved via dirname(__file__). The **data**
(memory, _pending, .cache) lives under $CLAUDE_PROJECT_DIR. In a plugin these are two different
locations (scripts = plugin root, data = project root) -- never confuse them.
"""
import json
import fnmatch
import os
import re
import subprocess
import sys
import tempfile

# build.sh co-locates repo_identity in the same directory as this hook (same convention as reflect.py).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from repo_identity import ProjectMatcher
except ImportError:  # helper missing (e.g. a standalone copy) -- only the sweep is disabled, the
    # rest of the hook keeps working
    ProjectMatcher = None
try:
    from hook_io import emit_context, project_dir as hook_project_dir, trace_entry
except ImportError:
    def emit_context(event, text):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": event, "additionalContext": text}}))

    def hook_project_dir(data=None):
        return (os.environ.get("CLAUDE_PROJECT_DIR")
                or ((data or {}).get("cwd") if isinstance(data, dict) else None)
                or os.getcwd())

    def trace_entry(*_a, **_kw):
        pass

# Matches only the completed form, "the merge is done". Proposals, questions and negations are
# excluded ("머지하자" / "머지 언제해?" / "머지하지마", "is this merged?", "not merged yet").
#
# ⚠️ The Korean alternatives below are **matchers against real user input**, not output. Users of
# this harness type merge announcements in Korean, so these patterns must keep working even though
# everything this hook *emits* is English. Do not translate them.
MERGE_DONE = re.compile(
    r"(머지|병합)\s*(을|를)?\s*(했|함|완료|끝|됐|되었)"
    r"|\b(merge\s+(is\s+)?done|merge\s+completed|it('?s| is| has)?\s+merged|pr\s+#?\d+\s+(is\s+)?merged)\b",
    re.I,
)

REMIND = (
    "The retrospective for merged PR{detail} has not been done yet. "
    "Before starting new work, run the following first so this work's lessons are captured:\n"
    "- /feedback-review — review whether the corrections you received should be promoted to a rule "
    "or a skill\n"
    "- /memory-update — persist newly learned patterns and decisions into memory (including "
    "reviewing and promoting pending drafts)"
)

# Once this many _pending drafts have piled up, escalate the merge reminder to a firm "clean this up
# now".
DRAFT_BACKLOG_THRESHOLD = 8

# PR details cost one `gh pr view` per PR (up to 8 seconds). To avoid blocking SessionStart and
# UserPromptSubmit for long, only some are processed per run and the rest continue on the next hook
# invocation.
PR_SCAN_MAX_PER_RUN = 3

# Default exceptions that break the loop where a retrospection-output PR demands its own
# retrospective. Projects can extend or override this via .claude/memory/reflect-skip.json.
DEFAULT_REFLECT_SKIP = {
    # Only paths the harness **creates itself** belong here. Project files (CLAUDE.md, AGENTS.md,
    # .claude/skills/**, ...) are worth reflecting on to different degrees per project, so the
    # engine does not decide for them -- in this repository an AGENTS.md change was a major
    # decision (#105), while for another team the same file is boilerplate.
    # The broader list lives in project-template/.claude/memory/reflect-skip.json.
    "paths": [
        ".claude/memory/**",
        ".claude/handoff/**",
        ".agents/skills/**",
    ],
    # Incidental files excluded from the verdict entirely. Without this, a single `.gitignore` line
    # breaks all() and the retrospection loop starts spinning again (#130). But a `.gitignore` change
    # can also be **substantive** (what is tracked, artifact policy, line endings), so the engine
    # does not decide what counts as incidental. The mechanism ships, the list stays empty -- the
    # project fills it in.
    "ignore_paths": [],
    "labels": [
        "skip-reflect",
        "no-reflect",
    ],
    "commit_messages": [
        "[skip reflect]",
        "skip-reflect",
        "no-reflect",
    ],
}


def _auto_reflect_enabled():
    """Opt-in gate for the automatic retrospection job (which spawns `claude -p`). Off by default,
    so that installing alone never starts a background LLM job. Enabled when HARNESS_AUTO_REFLECT is
    1/true/on."""
    return os.environ.get("HARNESS_AUTO_REFLECT", "").strip().lower() in ("1", "true", "on", "yes")


def _pending_drafts(project_dir):
    """Relative paths of every draft (.md) under _pending/. Recurses into subdirectories -- reflect
    puts decision drafts in `_pending/decisions/`, so a non-recursive listdir would miss them."""
    d = _pending_dir(project_dir)
    out = []
    try:
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.endswith(".md"):
                    out.append(os.path.relpath(os.path.join(root, f), d))
    except Exception:
        return []
    return out


def _draft_count(project_dir):
    return len(_pending_drafts(project_dir))


def _remind_text(project_dir, detail):
    """The base retrospection reminder, plus a review/promotion escalation when the draft backlog is
    at or above the threshold."""
    text = REMIND.format(detail=detail)
    n = _draft_count(project_dir)
    if n >= DRAFT_BACKLOG_THRESHOLD:
        text += (
            f"\n\n⚠️ {n} automatic reflect drafts have piled up "
            f"(threshold {DRAFT_BACKLOG_THRESHOLD}). Before starting new work, use `/memory-update` "
            f"to review and promote (or reject) them and clear out _pending."
        )
    return text


def _cache_path(project_dir):
    return os.path.join(project_dir, ".claude/.cache/pr-merge-seen.json")


# Harness artifacts that must never be committed. **The engine enforces this** -- the .gitignore in
# project-template only exists once the user copies it, and the README presents that copy as an
# optional step. A user who did not copy it would commit these with `git add -A`.
LOCAL_EXCLUDE_ENTRIES = (
    ".claude/.cache/",              # runtime caches and logs
    ".claude/memory/_pending/",     # retrospection drafts — extracted from session conversations,
                                    # not yet reviewed by a human
    ".claude/memory/_rejected.md",  # the rejection ledger — closer to a record of work habits and
                                    # past mistakes (personal tier)
)


def _gitignore_literal(path):
    """Turn a repo-relative path into a literal gitignore pattern rather than a glob.

    Escapes the backslash first, then the glob, comment, negation and whitespace syntax characters.
    Escaping whitespace is strictly required only at the end, but handling all of it gives the same
    rule regardless of where in the segment it appears.
    """
    escaped = []
    for char in path:
        if char in "\\*?[]#! ":
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)


def _ensure_local_cache_exclude(project_dir):
    """Top up the local exclude file with the harness artifacts that must not be committed.

    The user's tracked .gitignore is never modified. Projects that are not git repositories, or that
    are read-only, pass through silently so the hook never blocks.

    WARNING: this is not only about caches. `_pending/` holds **drafts extracted from session
    conversations** and `_rejected.md` is the **list of lessons deliberately not kept** = a record of
    work habits and past mistakes. In a public repository they would be published as-is.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "--git-path",
                "info/exclude",
                "--show-prefix",
            ],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=3,
        )
        lines = result.stdout.splitlines()
        if result.returncode != 0 or not lines:
            return
        path = lines[0]
        prefix = lines[1] if len(lines) > 1 else ""
        if not os.path.isabs(path):
            path = os.path.join(project_dir, path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existing = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                existing = handle.read()
        have = set(existing.splitlines())
        entries = [_gitignore_literal(prefix + entry) for entry in LOCAL_EXCLUDE_ENTRIES]
        missing = [entry for entry in entries if entry not in have]
        if not missing:
            return
        with open(path, "a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            for entry in missing:
                handle.write(entry + "\n")
    except (OSError, subprocess.SubprocessError):
        pass


def _reflect_skip_config_path(project_dir):
    memory_dir = os.path.realpath(os.path.join(project_dir, ".claude/memory"))
    path = os.path.realpath(os.path.join(memory_dir, "reflect-skip.json"))
    if path == memory_dir or path.startswith(memory_dir + os.sep):
        return path
    return None


def _pending_dir(project_dir):
    return os.path.join(project_dir, ".claude/memory/_pending")


def _write_json_atomic(path, data):
    """Write to a temporary file in the same directory and rename. The rename is atomic.

    WARNING: this hook **can die at any moment** -- session end, host timeout. A plain
    `open(path, "w")` that dies between truncating and writing leaves a **truncated file** behind,
    and the next run reads it. If that state is interpreted as "empty" rather than "corrupt" (which
    is what used to happen), the entire retrospection backlog floods back in.

    Why the same directory: `os.replace` is atomic only within one filesystem.
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_state(cache):
    """None when there is no cache (= first run), otherwise {'seen': set, 'pending': list}.

    WARNING: **corruption is None too.** It used to return an empty state on a parse failure, but
    callers treat only None as "first run" and read an empty seen as "nothing has been reflected on
    yet". So one truncated cache turned **all 30 merged PRs into un-reflected ones** -- exactly the
    stampede the design claims to prevent.

    "Corrupt" and "never existed" are different events, but **the recovery is the same**: silently
    seed the current state and do not dig up the past. So returning the same value is correct.
    """
    if not os.path.exists(cache):
        return None
    try:
        with open(cache, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError("state must be an object")
        seen = d.get("seen", [])
        pending = d.get("pending", [])
        if not isinstance(seen, list) or not isinstance(pending, list):
            raise ValueError("seen and pending must be lists")
        if not all(isinstance(n, int) and not isinstance(n, bool) for n in seen + pending):
            raise ValueError("seen and pending must contain PR numbers")
        return {"seen": set(seen), "pending": list(pending)}
    except (json.JSONDecodeError, TypeError, ValueError):
        sys.stderr.write(
            "[pr-merge-reflect] cache is corrupt, reseeding as if this were the first run "
            "(the previous pending queue cannot be recovered)\n"
        )
        return None
    except OSError:
        # Never mistake a transient read failure for corruption and overwrite a healthy cache with a
        # reseed.
        sys.stderr.write(
            "[pr-merge-reflect] could not read the cache, skipping this state update\n")
        raise


def _save_state(cache, seen, pending):
    """seen keeps only the 200 most recent entries (to stop unbounded growth); pending keeps all."""
    try:
        _write_json_atomic(cache, {
            "seen": sorted(set(seen), reverse=True)[:200],
            "pending": sorted(set(pending), reverse=True),
        })
    except Exception as exc:
        # The hook has to be fail-open, but the fact that the state was not saved must be
        # diagnosable.
        sys.stderr.write(
            f"[pr-merge-reflect] failed to save the cache: {type(exc).__name__}\n")


def _recent_merged(project_dir):
    """Recently merged PRs as [(number, title)], or None on failure."""
    try:
        r = subprocess.run(
            ["gh", "pr", "list", "--state", "merged", "--limit", "30",
             "--json", "number,title"],
            cwd=project_dir, capture_output=True, text=True, timeout=6,
        )
        if r.returncode != 0:
            return None
        return [(int(p["number"]), p.get("title", "")) for p in json.loads(r.stdout)]
    except Exception:
        return None


def _load_reflect_skip_config(project_dir):
    cfg = {k: list(v) for k, v in DEFAULT_REFLECT_SKIP.items()}
    path = _reflect_skip_config_path(project_dir)
    if not path or not os.path.exists(path):
        return cfg
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return cfg
        if data.get("defaults") is False:
            # Do not restate the key list here -- when a key is added to the defaults this side
            # would silently lag behind and raise KeyError later (which nearly happened when
            # ignore_paths was added).
            cfg = {k: [] for k in DEFAULT_REFLECT_SKIP}
        for key in DEFAULT_REFLECT_SKIP:
            vals = data.get(key)
            if isinstance(vals, list):
                cfg[key].extend(v for v in vals if isinstance(v, str) and v.strip())
        for key in cfg:
            cfg[key] = list(dict.fromkeys(cfg[key]))
    except Exception:
        return cfg
    return cfg


def _pr_details(project_dir, num):
    """The details needed for the PR skip verdict. None on gh/network failure."""
    try:
        r = subprocess.run(
            ["gh", "pr", "view", str(num), "--json", "files,labels,commits"],
            cwd=project_dir, capture_output=True, text=True, timeout=8,
        )
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        files = [
            f.get("path") for f in data.get("files", [])
            if isinstance(f, dict) and isinstance(f.get("path"), str)
        ]
        labels = [
            l.get("name") for l in data.get("labels", [])
            if isinstance(l, dict) and isinstance(l.get("name"), str)
        ]
        messages = []
        for c in data.get("commits", []) or []:
            if not isinstance(c, dict):
                continue
            msg = c.get("messageHeadline") or ""
            body = c.get("messageBody") or ""
            if msg or body:
                # Not stripped: the skip verdict reads line 0 as the **subject**, so an empty
                # headline has to stay an empty first line rather than promoting the body's
                # first line into subject position.
                messages.append(msg + "\n" + body)
        return {"files": files, "labels": labels, "commit_messages": messages}
    except Exception:
        return None


def _matches_any(value, patterns):
    return any(fnmatch.fnmatch(value, p) for p in patterns)


# A commit marker only counts as a **directive** when it stands in a directive position. Matched as
# a plain substring anywhere in the message, a commit that merely *writes about* the marker skips
# its own PR -- PR #134 here was a 16-file source change that skipped itself because one body line
# explained `[skip reflect]` in prose (#130 follow-up).
#
# Two positions, and only these two:
#   1. anywhere in the **subject** (the first line) -- the familiar `[skip ci]` convention; and
#   2. a **standalone body line** whose entire stripped content is the marker.
# In the body that leaves prose out: surrounding words, a `>` quote prefix, backticks, a fenced
# example. The subject keeps no prose exemption beyond an exactly backticked occurrence -- that is
# the price of the `[skip ci]` convention, and writing about a marker in a subject line is rare. No
# step here infers intent from natural language; only position decides.
_FENCE_CHARS = ("`", "~")


def _fence_run(line):
    """`(char, length, tail)` when the line opens with a fence run of 3+, else None."""
    stripped = line.strip()
    for char in _FENCE_CHARS:
        if stripped.startswith(char * 3):
            length = len(stripped) - len(stripped.lstrip(char))
            return char, length, stripped[length:]
    return None


def _directive_lines(message):
    """The lines that may carry a directive, as `(text, is_subject)` pairs.

    Fenced blocks are dropped: a fenced example of the marker is documentation, not an instruction.
    Only the CommonMark closing rule is implemented -- a fence closes on the **same character**, a
    run at least as long as the opener, and nothing but whitespace after it. A boolean toggle was
    tried first and was wrong in all three of the ways that rule exists to prevent: a `~~~` line
    inside a ``` block, a ``` line inside a ```` block, and ``` ``` not a closing fence ``` all
    counted as closures and released the rest of the block, so a documented example skipped a real
    PR.

    Everything else about fences is deliberately left out (no indentation limit, no info-string
    validation, no list nesting) -- this is not a Markdown parser. An unclosed fence still swallows
    every later line, which can only produce *more* retrospectives, the direction this module
    chooses to fail in.
    """
    lines = message.split("\n")
    out = [(lines[0], True)]
    opener = None  # (char, length) of the fence currently open
    for line in lines[1:]:
        fence = _fence_run(line)
        if opener is None:
            if fence is not None:
                opener = (fence[0], fence[1])
                continue
            out.append((line, False))
        elif (fence is not None and fence[0] == opener[0] and fence[1] >= opener[1]
                and not fence[2].strip()):
            opener = None
        # Lines inside the fence, and the closing line itself, are never directives.
    return out


def _subject_matches(subject, pattern):
    """The pre-existing matching rules, now applied to the subject only.

    Bracketed patterns are plain substrings (word boundaries do not work around `[`/`]`); every
    other pattern still needs non-word, non-hyphen boundaries so `no-reflect` does not match
    `no-reflection`.
    """
    if pattern.startswith("[") and pattern.endswith("]"):
        matches = re.finditer(re.escape(pattern), subject)
    else:
        matches = re.finditer(rf"(?<![\w-]){re.escape(pattern)}(?![\w-])", subject)
    for m in matches:
        # A backticked occurrence is the marker being quoted: "docs: explain `[skip reflect]`"
        # writes about the marker, it does not ask for it.
        if subject[m.start() - 1:m.start()] == "`" and subject[m.end():m.end() + 1] == "`":
            continue
        return True
    return False


def _message_matches_any(message, patterns):
    """True when the commit message carries a skip directive for one of `patterns`.

    `message` and `patterns` come in lowercased from the caller -- matching stays case-insensitive.

    Patterns are used exactly as the project stored them; this gate never trims them. A standalone
    body line is compared **trimmed line against literal pattern**, so a padded pattern such as
    `"  [no-retro]  "` can only match from the subject. Trimming the pattern here would let it match
    body lines the old substring rule never matched -- a new skip, the one direction this change is
    not allowed to move in.
    """
    lines = _directive_lines(message)
    for pattern in patterns:
        if not pattern:
            continue
        for text, is_subject in lines:
            if is_subject:
                if _subject_matches(text, pattern):
                    return True
            elif text.strip() == pattern:
                return True
    return False


def _should_skip_reflect(project_dir, num):
    """Exclude retrospection-output PRs from the pending/reflect set.

    A failed verdict stays False (= do reflect). Missing an automation PR is the more conservative
    error than skipping the retrospective for real work.
    """
    cfg = _load_reflect_skip_config(project_dir)
    details = _pr_details(project_dir, num)
    if details is None:
        return False

    labels = {l.lower() for l in details["labels"]}
    label_patterns = [p.lower() for p in cfg["labels"]]
    if any(_matches_any(label, label_patterns) for label in labels):
        return True

    commit_patterns = [p.lower() for p in cfg["commit_messages"]]
    for message in details["commit_messages"]:
        low = message.lower()
        if _message_matches_any(low, commit_patterns):
            return True

    # Incidental files are removed from the verdict. One `.gitignore` line in the mix does not turn
    # a retrospection-output PR into a work PR -- that one line broke all() and made the
    # retrospective-of-a-retrospective loop spin (#130).
    ignore_patterns = cfg.get("ignore_paths") or []
    files = [p for p in details["files"] if not _matches_any(p, ignore_patterns)]

    # A PR with only incidental files gives no grounds for a verdict -- reflect on it (fail-open).
    path_patterns = cfg["paths"]
    if files and path_patterns and all(_matches_any(path, path_patterns) for path in files):
        return True

    return False


def _scan_reflectable(project_dir, nums, cache, seen, pending):
    """Inspect only a bounded number of unchecked PRs, persisting state after each one.

    `seen` means only "the skip verdict is finished for this PR". Adding PRs that are still beyond
    the per-run cap to seen would mean they are never inspected on later calls either -- a permanent
    omission. Conversely, saving right after each verdict means that if the hook is terminated
    mid-run, the same network work is not repeated from scratch.
    """
    processed = 0
    for num in nums:
        if num in seen:
            continue
        if processed >= PR_SCAN_MAX_PER_RUN:
            break
        if not _should_skip_reflect(project_dir, num):
            pending.append(num)
        seen.add(num)
        processed += 1
        _save_state(cache, seen, pending)
    return seen, pending


def _detail(pending, titles):
    if not pending:
        return ""
    parts = []
    for n in sorted(pending, reverse=True)[:5]:
        t = titles.get(n)
        parts.append(f"#{n} {t}".strip() if t else f"#{n}")
    return " — " + ", ".join(parts)


def _emit(event_name, text):
    emit_context(event_name, text)


# ---------- Automatic retrospection job (B) ----------

def _reflect_script():
    """Absolute path to the co-located reflect.py. In a plugin deployment it sits in the same
    directory as this hook. (The original tutti version assumed it lived under project_dir, but in a
    plugin the scripts are outside the project.)"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "reflect.py")


def _transcript_path(data, project_dir):
    """Path to the current session transcript .jsonl. The hook input's transcript_path wins."""
    tp = data.get("transcript_path")
    if tp and os.path.exists(tp):
        return tp
    sid = data.get("session_id")
    if not sid:
        return None
    enc = project_dir.replace("/", "-").replace(".", "-")  # /a/b.c → -a-b-c
    cand = os.path.expanduser(f"~/.claude/projects/{enc}/{sid}.jsonl")
    return cand if os.path.exists(cand) else None


def _run_reflect(transcript, project_dir, label="claude"):
    """Run reflect.py detached (fire-and-forget). Shared by Claude transcripts and Codex rollouts.

    stdout/stderr go to .claude/.cache/reflect.log (observability): the start time, the label, the
    transcript and reflect.py's result summary ([reflect] N draft(s) / no drafts / an error) are
    recorded so it can be checked after the fact.
    """
    script = _reflect_script()
    if not os.path.exists(script) or not transcript or not os.path.exists(transcript):
        return False  # could not spawn -> tell the caller not to mark it seen (leaves a retry)
    try:
        from datetime import datetime
        log_path = os.path.join(project_dir, ".claude/.cache/reflect.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        logf = open(log_path, "a", encoding="utf-8")
        logf.write(f"\n==== {datetime.now():%Y-%m-%d %H:%M:%S} reflect started [{label}] "
                   f"(transcript={os.path.basename(transcript)}) ====\n")
        logf.flush()
        subprocess.Popen(
            ["python3", script, "--transcript", transcript],
            cwd=project_dir,
            env={**os.environ, "REFLECT_JOB": "1"},  # makes the nested claude's hook no-op
            stdout=logf, stderr=logf,  # a log rather than DEVNULL -- so the run/result/errors are
                                       # observable
            start_new_session=True,  # keeps running after the session is closed
        )
        return True  # spawn succeeded (the job's own result is async -- check reflect.log)
    except Exception:
        return False


def _spawn_reflect_job(data, project_dir):
    """Run the retrospection job on the current Claude session transcript. No-op when the opt-in is
    off."""
    if not _auto_reflect_enabled():
        return
    _run_reflect(_transcript_path(data, project_dir), project_dir, label="claude")


def _announce_pending_drafts(project_dir):
    d = _pending_dir(project_dir)
    if not os.path.isdir(d):
        return
    drafts = _pending_drafts(project_dir)  # recursive -- includes drafts under decisions/
    if not drafts:
        return
    escalate = (" ⚠️ The backlog is large, so clearing it before new work is recommended."
                if len(drafts) >= DRAFT_BACKLOG_THRESHOLD else "")
    _emit(
        "SessionStart",
        f"{len(drafts)} self-improvement retrospection draft(s) are waiting in "
        f"`.claude/memory/_pending/` ({', '.join(sorted(drafts)[:5])}).{escalate} "
        f"Suggest a review to the user — `/memory-update` reviews and promotes (or rejects) them. "
        f"Lessons go to auto-memory/MEMORY.md, and decision (ADR, `decisions/`) drafts are filed "
        f"into shared memory (`decisions/` + INDEX).",
    )


# ---------- Retrospection for standalone Codex sessions (the SessionStart sweep) ----------

CODEX_SWEEP_RECENT_DAYS = 14    # only rollouts from the last N days -- this is the cost ceiling
                                # (reading the first line of 14 days' worth)
CODEX_SWEEP_MIN_IDLE_MIN = 30   # modified within the last N minutes = possibly still running ->
                                # hold off reflecting/seeding (prevents partial retrospectives)
CODEX_SWEEP_MAX_PER_RUN = 3     # cap on retrospection spawns per sweep (prevents bursts)


def _codex_seen_path(project_dir):
    return os.path.join(project_dir, ".claude/.cache/codex-reflect-seen.json")


def _codex_meta(rollout_path):
    """The rollout's first line (session_meta) -> (session_id, cwd)."""
    try:
        with open(rollout_path, encoding="utf-8") as f:
            d = json.loads(f.readline())
        if d.get("type") == "session_meta":
            p = d.get("payload") or {}
            return p.get("id"), p.get("cwd")
    except Exception:
        pass
    return None, None


def _sweep_codex_sessions(project_dir, current_session_id=None):
    """Find this project's (by cwd) un-reflected Codex rollouts and spawn reflect. No-op when the
    opt-in is off.

    - First run: only seed the current ones as seen (no retrospection), to avoid a flood of
      retrospectives over past sessions.
    - Afterwards: reflect on un-reflected rollouts, capped per run (CODEX_SWEEP_MAX_PER_RUN); the
      rest wait for the next sweep.
    - Rollouts that are still in progress (recently modified) are excluded -- this prevents partial
      retrospectives and premature seen marking (the idle guard).
    - Matches when cwd is project_dir or below it (an in-project worktree). **External worktrees
      (Codex Desktop `~/.codex/worktrees/.../<repo>`) are not covered in v1 -- exact path or below
      only.**
    - Codex-inside-Claude invocations are separate rollouts and get picked up too, so some overlap
      with the Claude retrospective is possible (v1).
    - Fire-and-forget: if reflect.py fails asynchronously after a successful spawn (backend
      unavailable, a transient error), that session is not retried (it is already seen). Same limit
      as the Claude retrospection path. Marking seen only after confirmed completion needs a status
      callback and is follow-up work.
    """
    if not _auto_reflect_enabled():
        return
    if not os.path.exists(_reflect_script()):
        return  # the Codex 3a bundle deliberately ships without the automatic LLM retrospective.
    if ProjectMatcher is None:
        return
    import time
    base = os.path.expanduser("~/.codex/sessions")
    if not os.path.isdir(base):
        return
    try:
        now = time.time()
        recent_cutoff = now - CODEX_SWEEP_RECENT_DAYS * 86400
        idle_cutoff = now - CODEX_SWEEP_MIN_IDLE_MIN * 60  # modified more recently than this =
                                                           # possibly still running -> exclude
        # Walking only the date directories (YYYY/MM/DD) would **miss a session that started long
        # ago and was resumed recently** (they are stored under their start date). Like
        # handoff.py's _recent_codex_rollouts, walk the whole tree but filter by mtime -- only the
        # files that pass the mtime filter are opened, so the cost stays at stat level.
        rollouts = []  # (mtime, path) -- only the last N days and idle enough to look finished
        for directory, _dirs, names in os.walk(base):
            for fn in names:
                if not (fn.startswith("rollout-") and fn.endswith(".jsonl")):
                    continue
                fp = os.path.join(directory, fn)
                try:
                    mt = os.path.getmtime(fp)
                except OSError:
                    continue
                if recent_cutoff <= mt <= idle_cutoff:
                    rollouts.append((mt, fp))
        rollouts.sort(reverse=True)  # newest first

        # Observe the worktrees now and record them in the alias cache -- so they can still be
        # traced back after they are removed.
        matcher = ProjectMatcher(project_dir)
        matcher.record_worktrees()

        seen_path = _codex_seen_path(project_dir)
        # WARNING: first_run must **not** be decided by file existence. With a truncated file that
        # becomes "not the first run + empty seen", so already-reflected rollouts are reflected on
        # again, and the save below keeps only the new sids, **throwing the entire previous record
        # away.** It does not self-heal and it produces duplicates as it walks the backlog.
        # It is "not the first run" only when the read succeeded -- corruption is treated like a
        # first run and seeded silently.
        seen_list = None
        if os.path.exists(seen_path):
            try:
                with open(seen_path, encoding="utf-8") as f:
                    seen_list = list(json.load(f))
            except Exception:
                sys.stderr.write(
                    "[pr-merge-reflect] codex seen cache is corrupt, reseeding\n")
        first_run = seen_list is None
        if first_run:
            seen_list = []
        seen = set(seen_list)  # for membership lookups. seen_list is in insertion (processing)
                               # order -- capping keeps the newest.

        # Apply the project (cwd) filter **before** the cap -- so that sessions from other repos
        # cannot push this repo's out. Read the meta of all 14 days' worth and collect only this
        # project's un-reflected ones (newest first). Only the number of retrospectives is limited
        # below.
        fresh = []  # (sid, fp): this project + not yet reflected on
        for _, fp in rollouts:
            sid, cwd = _codex_meta(fp)
            # Judged by git repository identity, not by path prefix -- so a worktree outside the
            # project folder (`~/.codex/worktrees/`, a sibling `.agent-worktrees/`) is caught too.
            if sid and sid != current_session_id and sid not in seen and matcher.belongs(cwd):
                fresh.append((sid, fp))

        if first_run:
            # Seed only (no retrospection over the past). fresh is newest-first, so append from the
            # oldest so the newest ends up at the tail (capping keeps the newest).
            for sid, _fp in reversed(fresh):
                if sid not in seen:
                    seen.add(sid); seen_list.append(sid)
        else:
            for sid, fp in fresh[:CODEX_SWEEP_MAX_PER_RUN]:
                if _run_reflect(fp, project_dir, label=f"codex:{sid[:8]}"):
                    # Marked seen only on a successful spawn -- a failure is retried next sweep.
                    seen.add(sid); seen_list.append(sid)

        os.makedirs(os.path.dirname(seen_path), exist_ok=True)
        # Keep the newest 500 in insertion order (prevents unbounded growth).
        _write_json_atomic(seen_path, seen_list[-500:])
    except Exception:
        pass


# ---------- Event handlers ----------

def _on_session_start(project_dir, cache, data=None):
    merged = _recent_merged(project_dir)
    if merged is not None:
        nums = [n for n, _ in merged]
        try:
            state = _load_state(cache)
            if state is None:
                # First run: only seed the current merge state (prevents queueing a flood of old
                # PRs).
                _save_state(cache, set(nums), [])
            else:
                _scan_reflectable(
                    project_dir, nums, cache, set(state["seen"]), list(state["pending"])
                )
        except OSError:
            # A transient I/O failure on the state file only skips this PR update. The draft
            # announcement and the Codex sweep below are independent features, so they are not
            # blocked along with it.
            pass
    # If an earlier job left drafts behind, recommend a review.
    _announce_pending_drafts(project_dir)
    # Reflect on this project's un-reflected standalone Codex sessions (opt-in).
    _sweep_codex_sessions(project_dir, (data or {}).get("session_id"))


def _git_toplevel(path):
    """Keep the project cache at the repository root even when the Codex payload cwd is a
    subdirectory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=path,
            capture_output=True, text=True, timeout=3,
        )
        top = result.stdout.strip()
        if result.returncode == 0 and top:
            return os.path.normpath(top)
    except Exception:
        pass
    return os.path.normpath(path)


def _resolved_project_dir(data):
    """Preserve Claude's explicit path; normalise only the Codex payload cwd to the repository
    root."""
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return os.path.normpath(hook_project_dir(data))
    return _git_toplevel(hook_project_dir(data))


def _pr_is_merged(project_dir, num):
    """Check whether the PR number is actually MERGED. gh/network failures return False
    (conservative)."""
    try:
        state = subprocess.run(
            ["gh", "pr", "view", str(num), "--json", "state", "-q", ".state"],
            cwd=project_dir, capture_output=True, text=True, timeout=8,
        ).stdout.strip().upper()
        return state == "MERGED"
    except Exception:
        return False


def _merge_statement(cmd):
    """Return the statement that actually starts with `gh pr merge` -- this rules out false
    positives from `echo "gh pr merge 5"`, from `grep`, and from strings inside comments. Splits on
    `;`, newlines, `&&`, `||` and `|`, and looks only at the head of each fragment (ignoring leading
    whitespace)."""
    for stmt in re.split(r"[;\n]|&&|\|\|?", cmd):
        if re.match(r"\s*gh\s+pr\s+merge\b", stmt):
            return stmt
    return ""


def _looks_like_merge(cmd):
    return bool(_merge_statement(cmd))


def _on_post_tool(data, project_dir, cache):
    if data.get("tool_name") != "Bash":
        return
    cmd = data.get("tool_input", {}).get("command", "")
    stmt = _merge_statement(cmd)
    if not stmt:
        return
    # The PR number can appear before or after the flags: `gh pr merge 42 --squash` /
    # `gh pr merge --squash 42`.
    m = re.search(r"gh\s+pr\s+merge\b[^\d]*(\d+)", stmt)
    num = int(m.group(1)) if m else None
    # Queue and spawn only after confirming it is actually MERGED. A bare `gh pr merge` (current
    # branch, no number) cannot be verified, so it is held back -- the SessionStart sweep or the
    # user's own "I merged it" message picks it up later.
    if num is None or not _pr_is_merged(project_dir, num) or _should_skip_reflect(project_dir, num):
        return
    # The cache is only created by the SessionStart seeding (to prevent bulk reporting), so if it
    # is absent, hold off on queueing.
    if os.path.exists(cache):
        state = _load_state(cache)
        # A corrupt cache (None) is not overwritten with an empty state. The next SessionStart has
        # to silently reseed all recent merges, otherwise old PRs would re-enter pending on every
        # call.
        if state is not None:
            _save_state(cache, state["seen"] | {num}, state["pending"] + [num])
    # The current session is the work session -> run the automatic retrospection job (opt-in).
    _spawn_reflect_job(data, project_dir)


def _on_user_prompt(data, project_dir, cache):
    prompt = data.get("prompt", "") or ""
    merge_done = bool(MERGE_DONE.search(prompt))
    state = _load_state(cache)

    if merge_done:
        # The user said "I merged it" themselves -- the strongest signal. Treat the current session
        # as the work session and run the job.
        merged = _recent_merged(project_dir)
        if state is None:
            if merged is not None:
                # Seed the old PRs silently, but put the single newest PR -- the one the user just
                # said they merged -- through the real skip verdict. The newest has to be excluded
                # and saved first so it is not lost if we terminate mid-run.
                latest = [merged[0][0]] if merged else []
                seen = {n for n, _ in merged if n not in latest}
                pending = []
                _save_state(cache, seen, pending)
                seen, pending = _scan_reflectable(
                    project_dir, latest, cache, seen, pending
                )
                if pending:
                    titles = {n: t for n, t in merged}
                    _emit("UserPromptSubmit", _remind_text(project_dir, _detail(pending, titles)))
                    _spawn_reflect_job(data, project_dir)
                    _save_state(cache, seen, [])
                return
            _emit("UserPromptSubmit", _remind_text(project_dir, ""))
            _spawn_reflect_job(data, project_dir)
        else:
            seen, pending = set(state["seen"]), list(state["pending"])
            titles = {}
            if merged is not None:
                titles = {n: t for n, t in merged}
                seen, pending = _scan_reflectable(
                    project_dir, [n for n, _ in merged], cache, seen, pending
                )
            if pending:
                _emit("UserPromptSubmit", _remind_text(project_dir, _detail(pending, titles)))
                _spawn_reflect_job(data, project_dir)
            elif merged is None:
                _emit("UserPromptSubmit", _remind_text(project_dir, ""))
                _spawn_reflect_job(data, project_dir)
            _save_state(cache, seen, [])  # cleared once delivered
        return

    # An ordinary prompt (starting new work, etc.): if un-reflected PRs have piled up, reflect first
    # (reminder only). This is the cross-session case, so the current transcript is not the work
    # session -> no job is spawned.
    if state and state["pending"]:
        _emit("UserPromptSubmit", _remind_text(project_dir, _detail(state["pending"], {})))
        _save_state(cache, state["seen"], [])


def main():
    # Recursion guard: the nested claude inside the retrospection job (backend=claude) -> the whole
    # hook no-ops.
    if os.environ.get("REFLECT_JOB"):
        sys.exit(0)

    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    event = data.get("hook_event_name", "")
    trace_entry(__file__, event)
    # normpath: normalisation such as stripping a trailing slash (so Codex in-project matching is
    # not broken by a trailing separator).
    project_dir = _resolved_project_dir(data)
    cache = _cache_path(project_dir)

    # If this project does not use the harness memory system (no .claude/memory), no-op entirely.
    # This stops gh polling (a several-second block) and the Codex directory walk from running at
    # every session start in a repo that does not use them.
    if not os.path.isdir(os.path.join(project_dir, ".claude/memory")):
        sys.exit(0)

    try:
        _ensure_local_cache_exclude(project_dir)
        if event == "SessionStart":
            _on_session_start(project_dir, cache, data)
        elif event == "PostToolUse":
            _on_post_tool(data, project_dir, cache)
        elif event == "UserPromptSubmit":
            _on_user_prompt(data, project_dir, cache)
    except Exception:
        pass  # never block the session or the prompt, under any circumstances

    sys.exit(0)


if __name__ == "__main__":
    main()
