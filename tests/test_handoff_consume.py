#!/usr/bin/env python3
"""Does `consume` retire only the handoff that was loaded, and keep it recoverable? (#138)

A consumed handoff left in place is offered again by the next `load`, with stale done /
remaining / next entries. The cases come from the issue's done criteria:
  1) Only the consumed file goes; other branches' handoffs stay.
  2) The next `load` no longer offers it.
  3) Nothing is removed when there is no file, or when it cannot be tied to what was loaded
     (changed since `load`, or git state unreadable).
Plus the issue's open question: a file git history cannot bring back (untracked, staged
only, modified after commit) is archived before removal, and nothing is committed.

Runs on a real temporary git repository, with gh, transcripts and HOME isolated as in
test_handoff_commit_state.py.
"""
import importlib.util
import os
import re
import subprocess
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "handoff", ROOT / "core" / "scripts" / "handoff.py"
)
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)

FAKE_FACTS = {
    "branch": "fake",
    "status": "(none)",
    "stat_unstaged": "(none)",
    "stat_staged": "(none)",
    "ahead": "(none)",
    "pr": "(none, or lookup failed)",
}
FINGERPRINT = re.compile(r"consume --expect`\): `([0-9a-f]{64})`")


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


class _Args:
    def __init__(self, **kw):
        self.project_dir = None
        self.agent = "claude"
        self.summary = self.done = self.next = self.verify = None
        self.deep = False
        self.transcript = None
        self.expect = None
        for k, v in kw.items():
            setattr(self, k, v)


class HandoffConsumeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)
        self.outside = tempfile.TemporaryDirectory()
        self.home = os.path.realpath(self.outside.name)
        _git(["init", "-b", "main"], self.repo)
        _git(["config", "user.email", "t@example.com"], self.repo)
        _git(["config", "user.name", "t"], self.repo)
        Path(self.repo, "f.txt").write_text("hi\n")
        _git(["add", "."], self.repo)
        _git(["commit", "-m", "init"], self.repo)

    def tearDown(self):
        self.tmp.cleanup()
        self.outside.cleanup()

    def _run(self, fn, args):
        out, err = StringIO(), StringIO()
        ctxs = [
            patch.dict(os.environ,
                       {"CLAUDE_PROJECT_DIR": self.repo, "HOME": self.home,
                        "PATH": os.environ.get("PATH", "")},
                       clear=True),
            patch.object(handoff, "git_facts", lambda root: dict(FAKE_FACTS)),
            patch.object(handoff, "transcript_hint", lambda root: []),
            patch("sys.stdout", out),
            patch("sys.stderr", err),
        ]
        for c in ctxs:
            c.start()
        try:
            rc = fn(args)
        finally:
            for c in reversed(ctxs):
                c.stop()
        return rc, out.getvalue(), err.getvalue()

    def _save(self):
        rc, _, _ = self._run(handoff.cmd_save, _Args(summary="s", done="- d", next="- n"))
        self.assertEqual(rc, 0)

    def _load_fingerprint(self):
        rc, out, _ = self._run(handoff.cmd_load, _Args())
        self.assertEqual(rc, 0)
        m = FINGERPRINT.search(out)
        self.assertIsNotNone(m, "load must print the fingerprint consume expects")
        return m.group(1)

    def _consume(self, expect):
        return self._run(handoff.cmd_consume, _Args(expect=expect))

    def _target(self):
        return handoff.handoff_path(self.repo, handoff.current_branch(self.repo))

    def _rel(self):
        return os.path.relpath(self._target(), self.repo).replace(os.sep, "/")

    def _archive_dir(self):
        return Path(self.repo, ".git", "agent-harness", "handoff-archive")

    def _archived(self):
        d = self._archive_dir()
        return sorted(d.iterdir()) if d.is_dir() else []

    def _assert_retired(self, out, body):
        self.assertFalse(os.path.exists(self._target()))
        archived = self._archived()
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), body)
        self.assertIn(str(archived[0]), out)
        # Done criterion 2: the next load no longer offers it.
        _, loaded, _ = self._run(handoff.cmd_load, _Args())
        self.assertIn("Handoff file: none", loaded)

    # ---------- each git state is archived, then removed ----------

    def test_untracked_is_archived_then_removed(self):
        self._save()
        body = Path(self._target()).read_bytes()
        rc, out, _ = self._consume(self._load_fingerprint())
        self.assertEqual(rc, 0)
        self._assert_retired(out, body)

    def test_staged_new_is_unstaged_archived_and_removed(self):
        self._save()
        _git(["add", "--", self._rel()], self.repo)
        body = Path(self._target()).read_bytes()
        rc, out, _ = self._consume(self._load_fingerprint())
        self.assertEqual(rc, 0)
        self._assert_retired(out, body)
        # No dangling "added" entry left in the index.
        self.assertEqual(_git(["status", "--porcelain"], self.repo).strip(), "")

    def test_staged_copy_differing_from_disk_is_kept(self):
        """Unstaging would drop a staged body that exists nowhere else (Codex review on
        #138), so a staged copy that differs from the loaded file blocks the removal."""
        self._save()
        _git(["add", "--", self._rel()], self.repo)
        staged = _git(["show", ":" + self._rel()], self.repo)
        with open(self._target(), "a", encoding="utf-8") as f:
            f.write("\nedited after staging\n")
        rc, _, err = self._consume(self._load_fingerprint())
        self.assertEqual(rc, 1)
        self.assertIn("staged copy", err)
        self.assertTrue(os.path.exists(self._target()))
        self.assertEqual(_git(["show", ":" + self._rel()], self.repo), staged)

    def test_committed_deletion_is_left_unstaged_and_uncommitted(self):
        self._save()
        _git(["add", "--", self._rel()], self.repo)
        _git(["commit", "-m", "handoff"], self.repo)
        head = _git(["rev-parse", "HEAD"], self.repo)
        body = Path(self._target()).read_bytes()
        rc, out, _ = self._consume(self._load_fingerprint())
        self.assertEqual(rc, 0)
        self._assert_retired(out, body)
        self.assertEqual(_git(["rev-parse", "HEAD"], self.repo), head)
        self.assertEqual(_git(["status", "--porcelain"], self.repo), f" D {self._rel()}\n")
        self.assertIn("restore --source=HEAD", out)

    def test_modified_after_commit_archives_the_working_copy(self):
        self._save()
        _git(["add", "--", self._rel()], self.repo)
        _git(["commit", "-m", "handoff"], self.repo)
        with open(self._target(), "a", encoding="utf-8") as f:
            f.write("\nedited after commit\n")
        body = Path(self._target()).read_bytes()
        rc, out, _ = self._consume(self._load_fingerprint())
        self.assertEqual(rc, 0)
        self._assert_retired(out, body)

    # ---------- nothing removed when it cannot be tied to the load ----------

    def test_missing_file_removes_nothing(self):
        rc, out, _ = self._consume("0" * 64)
        self.assertEqual(rc, 0)
        self.assertIn("nothing to retire", out)
        self.assertEqual(self._archived(), [])

    def test_resaved_since_load_is_kept(self):
        self._save()
        fp = self._load_fingerprint()
        with open(self._target(), "a", encoding="utf-8") as f:
            f.write("\nsaved again by another session\n")
        rc, _, err = self._consume(fp)
        self.assertEqual(rc, 1)
        self.assertIn("changed since", err)
        self.assertTrue(os.path.exists(self._target()))
        self.assertEqual(self._archived(), [])

    def test_save_landing_after_the_check_is_kept(self):
        """A save between the fingerprint check and the removal must survive: only the
        body that was checked is archived and removed (Codex review on #138)."""
        self._save()
        fp = self._load_fingerprint()
        old_body = Path(self._target()).read_bytes()
        real_archive_dir = handoff._archive_dir

        def save_meanwhile(root):
            rc, _, _ = self._run(handoff.cmd_save, _Args(summary="newer", done="- d2"))
            self.assertEqual(rc, 0)
            return real_archive_dir(root)

        with patch.object(handoff, "_archive_dir", save_meanwhile):
            rc, _, _ = self._consume(fp)
        self.assertEqual(rc, 0)
        self.assertIn("newer", Path(self._target()).read_text(encoding="utf-8"))
        self.assertEqual([p.read_bytes() for p in self._archived()], [old_body])

    def test_save_leaves_no_temporary_file(self):
        self._save()
        self.assertEqual(os.listdir(os.path.dirname(self._target())),
                         [os.path.basename(self._target())])

    def test_unreadable_git_state_is_kept(self):
        self._save()
        fp = self._load_fingerprint()
        with patch.object(handoff, "handoff_sync_state", lambda root, path: "unknown"):
            rc, _, _ = self._consume(fp)
        self.assertEqual(rc, 1)
        self.assertTrue(os.path.exists(self._target()))
        self.assertEqual(self._archived(), [])

    def test_other_branch_handoff_is_kept(self):
        other = Path(self.repo, handoff.HANDOFF_DIR, "feature-x.md")
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text("other branch handoff\n", encoding="utf-8")
        self._save()
        rc, _, _ = self._consume(self._load_fingerprint())
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(self._target()))
        self.assertTrue(other.exists())

    def test_archive_sits_in_the_shared_git_dir_of_a_worktree(self):
        """From a linked worktree the copy goes to the common git dir, so removing the
        worktree does not take the only copy with it."""
        wt = os.path.join(self.home, "wt")
        _git(["worktree", "add", "-b", "feature-y", wt], self.repo)
        target = handoff.handoff_path(wt, "feature-y")
        os.makedirs(os.path.dirname(target))
        Path(target).write_text("worktree handoff\n", encoding="utf-8")
        fp = handoff._fingerprint(Path(target).read_bytes())
        rc, _, _ = self._run(handoff.cmd_consume, _Args(expect=fp, project_dir=wt))
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(target))
        self.assertEqual([p.read_text() for p in self._archived()], ["worktree handoff\n"])


if __name__ == "__main__":
    unittest.main()
