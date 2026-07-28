import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "core" / "scripts" / "merge_cleanup.py"
SPEC = importlib.util.spec_from_file_location("merge_cleanup", SCRIPT)
merge_cleanup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(merge_cleanup)


class LocalBranchCandidatesTest(unittest.TestCase):
    def test_combines_ancestry_and_same_repo_pr_candidates(self):
        prs = [
            {
                "number": 10,
                "headRefName": "squashed",
                "mergedAt": "2026-07-27T00:00:00Z",
                "isCrossRepository": False,
                "url": "https://example.test/pull/10",
            },
            {
                "number": 11,
                "headRefName": "fork-branch",
                "mergedAt": "2026-07-27T00:00:00Z",
                "isCrossRepository": True,
                "url": "https://example.test/pull/11",
            },
            {
                "number": 12,
                "headRefName": "missing-local",
                "mergedAt": None,
                "isCrossRepository": False,
                "url": "https://example.test/pull/12",
            },
        ]
        with (
            patch.object(merge_cleanup, "_current_branch", return_value="feature/current"),
            patch.object(
                merge_cleanup,
                "_local_branches",
                return_value={
                    "main",
                    "feature/current",
                    "ancestor",
                    "squashed",
                    "fork-branch",
                    "unrelated",
                },
            ),
            patch.object(
                merge_cleanup, "_merged_local_branches", return_value=["ancestor"]
            ),
            patch.object(merge_cleanup, "_recent_prs", side_effect=[prs, []]),
        ):
            result = merge_cleanup._local_branch_candidates(
                "/repo", "owner/repo", "origin/main", "main", 20
            )

        self.assertEqual(["ancestor", "squashed"], [row["branch"] for row in result])
        self.assertFalse(result[0]["force"])
        self.assertEqual("ancestor", result[0]["reason"])
        self.assertTrue(result[1]["force"])
        self.assertEqual(10, result[1]["pr"])
        self.assertEqual("merged", result[1]["state"])

    def test_closed_pr_is_reported_as_force_candidate(self):
        closed = {
            "number": 20,
            "headRefName": "abandoned",
            "mergedAt": None,
            "isCrossRepository": False,
            "url": "https://example.test/pull/20",
        }
        with (
            patch.object(merge_cleanup, "_current_branch", return_value="main"),
            patch.object(
                merge_cleanup, "_local_branches", return_value={"main", "abandoned"}
            ),
            patch.object(merge_cleanup, "_merged_local_branches", return_value=[]),
            patch.object(merge_cleanup, "_recent_prs", side_effect=[[], [closed]]),
        ):
            result = merge_cleanup._local_branch_candidates(
                "/repo", "owner/repo", "origin/main", "main", 20
            )

        self.assertEqual("closed", result[0]["state"])
        self.assertTrue(result[0]["force"])


class RenderTest(unittest.TestCase):
    def test_uses_force_delete_only_for_pr_based_candidates(self):
        result = {
            "repo": "owner/repo",
            "project_dir": "/repo",
            "default_branch": "main",
            "cleanup_base_ref": "origin/main",
            "sync": {"ahead": 0, "behind": 0},
            "fetch": {"ran": False, "ok": None},
            "local_merged_branches": ["ancestor", "squashed"],
            "local_branch_candidates": [
                {"branch": "ancestor", "force": False},
                {
                    "branch": "squashed",
                    "force": True,
                    "pr": 10,
                    "state": "merged",
                    "url": "https://example.test/pull/10",
                },
            ],
            "remote_branch_candidates": [],
            "closing_issue_candidates": [],
            "worktree_candidates": [],
            "untracked": [],
        }

        output = merge_cleanup.render(result)

        self.assertIn("git branch -d ancestor", output)
        self.assertIn("git branch -D squashed", output)
        self.assertIn("squash/closed PR", output)


class WorktreeTest(unittest.TestCase):
    def test_pr_based_local_candidate_enables_worktree_cleanup(self):
        porcelain = "\n".join(
            [
                "worktree /repo",
                "HEAD abc",
                "branch refs/heads/main",
                "",
                "worktree /tmp/squashed",
                "HEAD def",
                "branch refs/heads/squashed",
            ]
        )
        with patch.object(merge_cleanup, "_out", return_value=porcelain):
            result = merge_cleanup._worktrees("/repo", ["squashed"])

        self.assertEqual(
            [{"path": "/tmp/squashed", "branch": "squashed"}],
            result,
        )


if __name__ == "__main__":
    unittest.main()
