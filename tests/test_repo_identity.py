#!/usr/bin/env python3
"""repo_identity: is a worktree **outside** the project folder recognized as the same repository?

Regression under test: a path-prefix check (`cwd.startswith(project_dir + os.sep)`) dropped
the sessions of external worktrees entirely (issue #75). test_sibling_worktree_belongs below
is the reproduction.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core", "scripts"))
from repo_identity import ProjectMatcher, git_common_dir, worktree_roots, _is_within  # noqa: E402


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True,
                   capture_output=True, text=True)


class RepoIdentityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.realpath(self.tmp.name)
        self.repo = os.path.join(self.base, "myrepo")
        os.makedirs(self.repo)
        _git(["init", "-b", "main"], self.repo)
        _git(["config", "user.email", "t@example.com"], self.repo)
        _git(["config", "user.name", "t"], self.repo)
        with open(os.path.join(self.repo, "f.txt"), "w") as f:
            f.write("hi\n")
        _git(["add", "."], self.repo)
        _git(["commit", "-m", "init"], self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def _add_worktree(self, path, branch):
        _git(["worktree", "add", "-b", branch, path], self.repo)
        return os.path.realpath(path)

    # ---------- core regression ----------

    def test_sibling_worktree_belongs(self):
        """A worktree that is a **sibling** of the project folder is the same repository.

        The case a path-prefix check always rejected — the real situation from issue #75
        (`Repository/.agent-worktrees/...` vs `Repository/agent-harness`)."""
        wt = self._add_worktree(os.path.join(self.base, "wt-sibling"), "feat-a")
        m = ProjectMatcher(self.repo)
        self.assertFalse(wt.startswith(self.repo + os.sep),
                         "precondition: the worktree must not be under the project for this test to mean anything")
        self.assertTrue(m.belongs(wt))

    def test_far_away_worktree_belongs(self):
        """A worktree in a completely different tree is recognized too (the equivalent of Codex Desktop's `~/.codex/worktrees/<hash>`)."""
        far = os.path.join(self.base, "elsewhere", "deadbeef")
        os.makedirs(os.path.dirname(far))
        wt = self._add_worktree(far, "feat-b")
        self.assertTrue(ProjectMatcher(self.repo).belongs(wt))

    def test_subdir_of_worktree_belongs(self):
        """A session run from a subdirectory of the worktree is recognized (the agent cd'd there to work)."""
        wt = self._add_worktree(os.path.join(self.base, "wt-sub"), "feat-c")
        sub = os.path.join(wt, "nested")
        os.makedirs(sub)
        self.assertTrue(ProjectMatcher(self.repo).belongs(sub))

    def test_project_dir_itself_belongs(self):
        self.assertTrue(ProjectMatcher(self.repo).belongs(self.repo))

    # ---------- other repositories are excluded ----------

    def test_other_repo_excluded(self):
        other = os.path.join(self.base, "otherrepo")
        os.makedirs(other)
        _git(["init", "-b", "main"], other)
        self.assertFalse(ProjectMatcher(self.repo).belongs(other))

    def test_non_repo_excluded(self):
        plain = os.path.join(self.base, "plain")
        os.makedirs(plain)
        self.assertFalse(ProjectMatcher(self.repo).belongs(plain))

    def test_none_cwd_excluded(self):
        self.assertFalse(ProjectMatcher(self.repo).belongs(None))
        self.assertFalse(ProjectMatcher(self.repo).belongs(""))

    def test_sibling_prefix_lookalike_excluded(self):
        """`myrepo-evil` is not below `myrepo` — guards against a startswith false positive."""
        evil = self.repo + "-evil"
        os.makedirs(evil)
        _git(["init", "-b", "main"], evil)
        self.assertFalse(ProjectMatcher(self.repo).belongs(evil))

    # ---------- removed worktree: alias cache ----------

    def test_removed_worktree_resolved_via_alias(self):
        """A worktree removed after being observed is resolved from the alias cache.

        Once the path is gone there is nothing to ask git — the observation record is the
        only evidence left."""
        wt = self._add_worktree(os.path.join(self.base, "wt-gone"), "feat-d")
        m1 = ProjectMatcher(self.repo)
        self.assertTrue(m1.record_worktrees(), "the observation record must be persisted")

        _git(["worktree", "remove", "--force", wt], self.repo)
        self.assertFalse(os.path.exists(wt))

        m2 = ProjectMatcher(self.repo)  # a fresh instance, re-reading the cache from disk
        self.assertTrue(m2.belongs(wt))

    def test_unobserved_removed_worktree_not_guessed(self):
        """A path that vanished without ever being observed is not guessed at (no false positives)."""
        ghost = os.path.join(self.base, "never-seen")
        m = ProjectMatcher(self.repo)
        m.record_worktrees()
        self.assertFalse(m.belongs(ghost))

    def test_alias_cache_lives_in_git_common_dir(self):
        """The alias lives in the git common directory — never committed, shared by every worktree."""
        m = ProjectMatcher(self.repo)
        m.record_worktrees()
        expected = os.path.join(git_common_dir(self.repo), "agent-harness", "worktree-alias.json")
        self.assertTrue(os.path.exists(expected))

    def test_alias_shared_between_worktree_and_main(self):
        """The **main checkout** reads a record observed from a linked worktree.

        The case that breaks if the cache lives under project_dir: observe from a worktree
        → remove that worktree → the cache disappears with it and the main checkout can
        resolve nothing."""
        wt = self._add_worktree(os.path.join(self.base, "wt-observer"), "feat-e")
        gone = self._add_worktree(os.path.join(self.base, "wt-doomed"), "feat-f")

        # The observer is the linked worktree, not the main checkout
        ProjectMatcher(wt).record_worktrees()

        _git(["worktree", "remove", "--force", gone], self.repo)
        self.assertFalse(os.path.exists(gone))

        # Look it up from the main checkout — it must see the same cache
        self.assertTrue(ProjectMatcher(self.repo).belongs(gone))

    def test_alias_survives_observing_worktree_removal(self):
        """The record survives even when the observing worktree itself is deleted (the cache is not inside it)."""
        wt = self._add_worktree(os.path.join(self.base, "wt-selfgone"), "feat-g")
        ProjectMatcher(wt).record_worktrees()
        _git(["worktree", "remove", "--force", wt], self.repo)
        self.assertTrue(ProjectMatcher(self.repo).belongs(wt))

    # ---------- lower-level helpers ----------

    def test_worktree_roots_includes_all(self):
        a = self._add_worktree(os.path.join(self.base, "wt-1"), "b1")
        b = self._add_worktree(os.path.join(self.base, "wt-2"), "b2")
        roots = worktree_roots(self.repo)
        self.assertIn(os.path.normcase(a), [os.path.normcase(r) for r in roots])
        self.assertIn(os.path.normcase(b), [os.path.normcase(r) for r in roots])

    def test_worktree_path_with_space(self):
        """A porcelain path containing a space still parses — the case where split() breaks."""
        wt = self._add_worktree(os.path.join(self.base, "wt with space"), "b3")
        self.assertTrue(ProjectMatcher(self.repo).belongs(wt))

    def test_git_common_dir_same_for_worktree(self):
        wt = self._add_worktree(os.path.join(self.base, "wt-id"), "b4")
        self.assertEqual(git_common_dir(self.repo), git_common_dir(wt))

    def test_git_common_dir_none_for_non_repo(self):
        plain = os.path.join(self.base, "nope")
        os.makedirs(plain)
        self.assertIsNone(git_common_dir(plain))

    def test_handoff_matcher_records_observations(self):
        """The fw/history path records observations as well.

        Auto-retrospective is off by default, so leaving the recording to it alone means the
        cache is never created — a user who never enables retrospectives would lose the
        ability to resolve removed worktrees entirely."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "core", "scripts"))
        import handoff

        gone = self._add_worktree(os.path.join(self.base, "wt-fw"), "feat-h")
        handoff._project_matcher(self.repo)          # what fw/history does
        _git(["worktree", "remove", "--force", gone], self.repo)

        self.assertTrue(ProjectMatcher(self.repo).belongs(gone))

    def test_is_within(self):
        self.assertTrue(_is_within("/a/b/c", "/a/b"))
        self.assertFalse(_is_within("/a/bc", "/a/b"))   # prefix false positive
        self.assertFalse(_is_within("/a/b", "/a/b"))    # a path is not below itself
        self.assertFalse(_is_within("/a/b", "/x/y"))


if __name__ == "__main__":
    unittest.main()
