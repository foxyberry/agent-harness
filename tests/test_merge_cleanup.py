import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "core" / "scripts" / "merge_cleanup.py"
SPEC = importlib.util.spec_from_file_location("merge_cleanup", SCRIPT)
merge_cleanup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(merge_cleanup)


class LocalBranchCandidatesTest(unittest.TestCase):
    def test_latest_pr_for_reused_branch_wins(self):
        older_merged = {
            "number": 60,
            "headRefName": "reused",
            "closedAt": "2026-07-20T00:00:00Z",
            "mergedAt": "2026-07-20T00:00:00Z",
            "isCrossRepository": False,
        }
        newer_closed = {
            "number": 61,
            "headRefName": "reused",
            "closedAt": "2026-07-27T00:00:00Z",
            "mergedAt": None,
            "isCrossRepository": False,
        }

        latest = merge_cleanup._latest_prs_by_branch(
            [older_merged, newer_closed]
        )

        self.assertEqual(61, latest["reused"]["number"])

    def test_combines_ancestry_and_same_repo_pr_candidates(self):
        prs = [
            {
                "number": 10,
                "headRefName": "squashed",
                "headRefOid": "squashed-tip",
                "mergedAt": "2026-07-27T00:00:00Z",
                "closedAt": "2026-07-27T00:00:00Z",
                "isCrossRepository": False,
                "url": "https://example.test/pull/10",
            },
            {
                "number": 11,
                "headRefName": "fork-branch",
                "headRefOid": "fork-tip",
                "mergedAt": "2026-07-27T00:00:00Z",
                "closedAt": "2026-07-27T00:00:00Z",
                "isCrossRepository": True,
                "url": "https://example.test/pull/11",
            },
            {
                "number": 12,
                "headRefName": "missing-local",
                "headRefOid": "missing-tip",
                "mergedAt": None,
                "closedAt": "2026-07-27T00:00:00Z",
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
            patch.object(merge_cleanup, "_out", return_value="squashed-tip"),
        ):
            result = merge_cleanup._local_branch_candidates(
                "/repo", prs, "origin/main", "main"
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
            "headRefOid": "closed-tip",
            "mergedAt": None,
            "closedAt": "2026-07-27T00:00:00Z",
            "isCrossRepository": False,
            "url": "https://example.test/pull/20",
        }
        with (
            patch.object(merge_cleanup, "_current_branch", return_value="main"),
            patch.object(
                merge_cleanup, "_local_branches", return_value={"main", "abandoned"}
            ),
            patch.object(merge_cleanup, "_merged_local_branches", return_value=[]),
            patch.object(merge_cleanup, "_out", return_value="closed-tip"),
        ):
            result = merge_cleanup._local_branch_candidates(
                "/repo", [closed], "origin/main", "main"
            )

        self.assertEqual("closed", result[0]["state"])
        self.assertTrue(result[0]["force"])

    def test_diverged_or_reused_branch_never_gets_force_delete(self):
        old_pr = {
            "number": 30,
            "headRefName": "reused",
            "headRefOid": "old-tip",
            "mergedAt": "2026-07-27T00:00:00Z",
            "closedAt": "2026-07-27T00:00:00Z",
            "isCrossRepository": False,
            "url": "https://example.test/pull/30",
        }
        with (
            patch.object(merge_cleanup, "_current_branch", return_value="main"),
            patch.object(
                merge_cleanup, "_local_branches", return_value={"main", "reused"}
            ),
            patch.object(merge_cleanup, "_merged_local_branches", return_value=[]),
            patch.object(merge_cleanup, "_out", return_value="new-local-tip"),
        ):
            result = merge_cleanup._local_branch_candidates(
                "/repo", [old_pr], "origin/main", "main"
            )

        self.assertEqual("pr-diverged", result[0]["reason"])
        self.assertFalse(result[0]["force"])

    def test_current_branch_is_excluded_even_when_pr_name_matches(self):
        pr = {
            "number": 40,
            "headRefName": "feature/current",
            "headRefOid": "tip",
            "mergedAt": "2026-07-27T00:00:00Z",
            "closedAt": "2026-07-27T00:00:00Z",
            "isCrossRepository": False,
        }
        with (
            patch.object(
                merge_cleanup, "_current_branch", return_value="feature/current"
            ),
            patch.object(
                merge_cleanup,
                "_local_branches",
                return_value={"main", "feature/current"},
            ),
            patch.object(merge_cleanup, "_merged_local_branches", return_value=[]),
        ):
            result = merge_cleanup._local_branch_candidates(
                "/repo", [pr], "origin/main", "main"
            )

        self.assertEqual([], result)


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
        self.assertIn("squash merge", output)

    def test_old_json_fallback_and_pr_query_warning(self):
        result = {
            "repo": "owner/repo",
            "project_dir": "/repo",
            "default_branch": "main",
            "cleanup_base_ref": "origin/main",
            "sync": {"ahead": 0, "behind": 0},
            "fetch": {"ran": False, "ok": None},
            "pr_query_ok": False,
            "local_merged_branches": ["ancestor"],
            "remote_branch_candidates": [],
            "closing_issue_candidates": [],
            "worktree_candidates": [],
            "untracked": [],
        }

        output = merge_cleanup.render(result)

        self.assertIn("GitHub PR 조회 실패", output)
        self.assertIn("git branch -d ancestor", output)

    def test_diverged_branch_renders_check_without_force_delete(self):
        result = {
            "repo": "owner/repo",
            "project_dir": "/repo",
            "default_branch": "main",
            "cleanup_base_ref": "origin/main",
            "sync": {"ahead": 0, "behind": 0},
            "fetch": {"ran": False, "ok": None},
            "local_merged_branches": ["reused"],
            "local_branch_candidates": [
                {
                    "branch": "reused",
                    "reason": "pr-diverged",
                    "force": False,
                    "pr": 30,
                    "state": "merged",
                }
            ],
            "remote_branch_candidates": [],
            "closing_issue_candidates": [],
            "worktree_candidates": [],
            "untracked": [],
        }

        output = merge_cleanup.render(result)

        self.assertIn("강제 삭제 제안 안 함", output)
        self.assertNotIn("git branch -D reused", output)


class RemoteBranchCandidatesTest(unittest.TestCase):
    def test_remote_reused_branch_does_not_get_delete_command(self):
        pr = {
            "number": 50,
            "headRefName": "reused",
            "headRefOid": "old-tip",
            "mergedAt": "2026-07-27T00:00:00Z",
            "closedAt": "2026-07-27T00:00:00Z",
            "isCrossRepository": False,
            "url": "https://example.test/pull/50",
        }
        with patch.object(
            merge_cleanup, "_remote_branches", return_value={"reused": "new-tip"}
        ):
            candidates = merge_cleanup._remote_branch_candidates("/repo", [pr])

        self.assertFalse(candidates[0]["tip_matches_pr"])

        result = {
            "repo": "owner/repo",
            "project_dir": "/repo",
            "default_branch": "main",
            "sync": {"ahead": 0, "behind": 0},
            "fetch": {"ran": False, "ok": None},
            "local_merged_branches": [],
            "remote_branch_candidates": candidates,
            "closing_issue_candidates": [],
            "worktree_candidates": [],
            "untracked": [],
        }
        output = merge_cleanup.render(result)
        self.assertIn("원격 tip 이 PR head 이후 변경됨", output)
        self.assertNotIn("git push origin --delete reused", output)


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
