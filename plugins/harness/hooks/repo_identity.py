#!/usr/bin/env python3
"""Repository identity — decides whether a session log's cwd is "a workspace of this project".

Why this is needed:
  Parallel agent work separates working trees with `git worktree`, and it is normal for a
  worktree to live **outside the project folder**:
    - Codex Desktop  : `~/.codex/worktrees/<hash>/`
    - user convention: `<sibling of the repo>/.agent-worktrees/<name>/`
    - arbitrary      : the user may pass any path at all
  A path-prefix test (`cwd.startswith(project_dir + os.sep)`) rejects all of these as
  "someone else's project". That is exactly how the PR #72 retrospective of this
  repository went missing in full.

Approach:
  Do not compare paths — **ask git directly**. `git rev-parse --git-common-dir` points at
  the original repository's `.git` no matter where the worktree lives. Equal values mean
  the same repository.

  If the cwd is already gone (after the worktree was removed) there is nothing left to
  ask. So each observation records `worktree path → identity` into an alias cache, and
  vanished paths are resolved from it afterwards. **A worktree that disappeared without
  ever being observed is unrecoverable** — we do not guess (no false positives).

Usage:
  m = ProjectMatcher(project_dir)
  m.belongs(cwd)          # → bool
  m.record_worktrees()    # record (observe) the current worktrees in the alias cache
"""
import json
import os
import subprocess
import time

GIT_TIMEOUT = 5           # cap on git calls — this runs inside hooks and must never hang
ALIAS_RETAIN_DAYS = 90    # alias retention: a removed worktree stays resolvable this long


def _norm(path):
    """Normalize a path: absorbs symlinks, `..`, trailing slashes and case differences.

    Missing normalization was the main reason startswith comparisons broke (the macOS
    `/tmp` → `/private/tmp` symlink being the classic case)."""
    if not path:
        return None
    try:
        return os.path.normcase(os.path.realpath(path))
    except (OSError, ValueError):
        return None


def _git(args, cwd):
    """Run git → stdout string. Failure, timeout and a missing git all yield None (never raises)."""
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def git_common_dir(path):
    """Common .git directory of the repository containing `path` (normalized absolute).
    None when it is not a repository.

    Even from a linked worktree this returns **the original repository's .git** — that is
    the identity. (Do not use `--git-dir`: it gives a per-worktree
    `.git/worktrees/<name>`.)"""
    if not path or not os.path.isdir(path):
        return None
    out = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], path)
    if not out:
        # Older git does not know --path-format → the result may be relative, so resolve
        # it against the cwd we asked from
        out = _git(["rev-parse", "--git-common-dir"], path)
        if out and not os.path.isabs(out):
            out = os.path.join(path, out)
    return _norm(out) if out else None


def worktree_roots(project_dir):
    """All worktree roots registered for this repository (normalized paths).

    The porcelain format is a list of records, each starting with a `worktree <path>`
    line. Paths may contain spaces, so parse by **stripping the prefix**, not split().
    `bare` records are not working trees and are excluded. `prunable`, `locked` and
    detached entries are still real working trees and are **not** excluded."""
    out = _git(["worktree", "list", "--porcelain"], project_dir)
    if not out:
        return []
    roots, current, is_bare = [], None, False
    for line in out.splitlines():
        if line.startswith("worktree "):
            if current and not is_bare:
                roots.append(current)
            current, is_bare = _norm(line[len("worktree "):]), False
        elif line.strip() == "bare":
            is_bare = True
    if current and not is_bare:
        roots.append(current)
    return [r for r in roots if r]


class ProjectMatcher:
    """Decides whether a cwd is a workspace of this project. git calls are cached and memoized.

    A single sweep checks the cwd of hundreds of rollouts, so calling git every time is
    expensive.
    - worktree list: once per instance
    - cwd → identity: memoized per path
    """

    def __init__(self, project_dir, alias_path=None):
        self.project_dir = _norm(project_dir)
        self.identity = git_common_dir(project_dir) if project_dir else None
        self._alias_path = alias_path or _default_alias_path(project_dir, self.identity)
        self._roots = None          # lazy: worktree_roots()
        self._alias = None          # lazy: on-disk cache
        self._identity_cache = {}   # normalized cwd → identity|None

    # ---------- internal lazy loaders ----------

    def _get_roots(self):
        if self._roots is None:
            self._roots = set(worktree_roots(self.project_dir)) if self.project_dir else set()
            if self.project_dir:
                self._roots.add(self.project_dir)
        return self._roots

    def _get_alias(self):
        if self._alias is None:
            self._alias = _load_alias(self._alias_path)
        return self._alias

    def _identity_of(self, cwd_norm):
        if cwd_norm not in self._identity_cache:
            self._identity_cache[cwd_norm] = git_common_dir(cwd_norm)
        return self._identity_cache[cwd_norm]

    # ---------- public API ----------

    def belongs(self, cwd):
        """True when cwd is a working tree of this project (main checkout or a worktree).

        Decision order — strongest evidence first:
          1. live path → ask git for the identity (most accurate)
          2. equals/inside a registered worktree root (in case the git call failed)
          3. alias cache (the only evidence left once the path is gone)
        If none of them match, False — we do not guess."""
        cwd_norm = _norm(cwd)
        if not cwd_norm or not self.project_dir:
            return False

        # 1) Live path → ask git directly. Accurate regardless of where the worktree is.
        if os.path.isdir(cwd_norm):
            ident = self._identity_of(cwd_norm)
            if ident and self.identity:
                return ident == self.identity
            # No git, or not a repository → fall through to the path-based checks below

        # 2) Containment relative to the registered worktree roots.
        #    commonpath, not startswith — prevents `/a/b` from swallowing `/a/bc`.
        for root in self._get_roots():
            if cwd_norm == root or _is_within(cwd_norm, root):
                return True

        # 3) Vanished worktree → resolve it from past observations.
        alias = self._get_alias()
        if alias.get("identity") and self.identity and alias["identity"] == self.identity:
            for path in alias.get("roots", {}):
                if cwd_norm == path or _is_within(cwd_norm, path):
                    return True
        return False

    def record_worktrees(self):
        """Record the current worktrees in the alias cache, so they resolve after removal.

        Call this from a point that runs regularly, such as SessionStart. Stale entries
        expire. Failures pass silently — a failed observation must not block the
        retrospective."""
        if not self.identity:
            return False
        alias = self._get_alias()
        if alias.get("identity") != self.identity:
            alias = {"identity": self.identity, "roots": {}}
        now = time.time()
        for root in self._get_roots():
            alias["roots"][root] = now
        cutoff = now - ALIAS_RETAIN_DAYS * 86400
        alias["roots"] = {p: ts for p, ts in alias["roots"].items() if ts >= cutoff}
        self._alias = alias
        return _save_alias(self._alias_path, alias)


def _is_within(child, parent):
    """Is child below parent? commonpath-based — no string-prefix false positives."""
    if not child or not parent:
        return False
    try:
        return os.path.commonpath([child, parent]) == parent and child != parent
    except ValueError:  # no common path at all, e.g. different drives
        return False


def _default_alias_path(project_dir, identity=None):
    """Alias cache location = **inside the git common directory** (`<repo>/.git/agent-harness/`).

    It must not live in the project's `.claude/.cache/`: when `project_dir` is itself a
    linked worktree the cache is created inside that worktree, and **removing the worktree
    removes the cache with it** — the record made for resolving vanished paths disappears
    exactly when it is needed. On top of that, the main checkout would read a different
    cache and the two would never see each other.

    The git common directory is shared by every worktree, survives worktree removal, and
    is not committed (no absolute paths end up in the repository)."""
    common = identity or git_common_dir(project_dir)
    if common:
        return os.path.join(common, "agent-harness", "worktree-alias.json")
    if not project_dir:
        return None
    # Not a git repository (tests, or an abnormal state) → fall back to a project-local cache
    return os.path.join(project_dir, ".claude", ".cache", "worktree-alias.json")


def _load_alias(path):
    if not path or not os.path.exists(path):
        return {"identity": None, "roots": {}}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("roots"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"identity": None, "roots": {}}


def _save_alias(path, alias):
    if not path:
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(alias, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False
