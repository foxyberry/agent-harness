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

    def test_closed_pr_never_bypasses_git_delete_safety(self):
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
        self.assertEqual("pr-closed", result[0]["reason"])
        self.assertFalse(result[0]["force"])

        report = {
            "repo": "owner/repo",
            "project_dir": "/repo",
            "default_branch": "main",
            "sync": {"ahead": 0, "behind": 0},
            "fetch": {"ran": False, "ok": None},
            "local_merged_branches": [],
            "local_branch_candidates": result,
            "remote_branch_candidates": [],
            "closing_issue_candidates": [],
            "worktree_candidates": [],
            "untracked": [],
        }
        output = merge_cleanup.render(report)
        self.assertIn("git branch -d abandoned", output)
        self.assertNotIn("git branch -D abandoned", output)

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
    def test_closed_remote_branch_never_gets_delete_command(self):
        pr = {
            "number": 51,
            "headRefName": "abandoned",
            "headRefOid": "tip",
            "mergedAt": None,
            "closedAt": "2026-07-27T00:00:00Z",
            "isCrossRepository": False,
            "url": "https://example.test/pull/51",
        }
        with patch.object(
            merge_cleanup, "_remote_branches", return_value={"abandoned": "tip"}
        ):
            candidates = merge_cleanup._remote_branch_candidates("/repo", [pr])

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
        self.assertIn("원격이 유일한 사본일 수 있음", output)
        self.assertNotIn("git push origin --delete abandoned", output)

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
    def test_only_merged_or_ancestry_candidates_enable_worktree_cleanup(self):
        candidates = [
            {"branch": "ancestor", "reason": "ancestor", "force": False},
            {"branch": "squashed", "reason": "pr", "force": True, "state": "merged"},
            {"branch": "closed", "reason": "pr-closed", "force": False, "state": "closed"},
            {
                "branch": "reused",
                "reason": "pr-diverged",
                "force": False,
                "state": "merged",
            },
        ]

        self.assertEqual(
            ["ancestor", "squashed"],
            merge_cleanup._safe_worktree_branches(candidates),
        )

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


class UnexplainedBranchTest(unittest.TestCase):
    """어느 후보에도 안 걸린 브랜치가 리포트에서 통째로 사라지던 문제 (이슈 #78).

    후보는 "main 의 조상" 또는 "조회해 온 PR 의 head 와 이름이 맞음" 두 경로로만 생긴다.
    둘 다 아닌 브랜치는 아무 섹션에도 안 나왔고, 그러면 "정리할 게 없다"로 읽힌다.
    """

    def test_local_and_remote_branches_without_a_candidate_are_surfaced(self):
        with (
            patch.object(merge_cleanup, "_current_branch", return_value="main"),
            patch.object(
                merge_cleanup,
                "_local_branches",
                return_value={"main", "feature/has-pr", "review/local-only"},
            ),
            patch.object(
                merge_cleanup,
                "_remote_branches",
                return_value={"main": "a", "feature/has-pr": "b", "old/forgotten": "c"},
            ),
        ):
            out = merge_cleanup._unexplained_branches(
                "/repo", [{"branch": "feature/has-pr"}], [{"branch": "feature/has-pr"}], "main"
            )

        self.assertEqual(["review/local-only"], out["local"])
        self.assertEqual(["old/forgotten"], out["remote"])

    def test_protected_and_current_branches_are_never_listed(self):
        with (
            patch.object(merge_cleanup, "_current_branch", return_value="work/now"),
            patch.object(
                merge_cleanup,
                "_local_branches",
                return_value={"main", "master", "develop", "work/now", "stray"},
            ),
            patch.object(merge_cleanup, "_remote_branches", return_value={"main": "a"}),
        ):
            out = merge_cleanup._unexplained_branches("/repo", [], [], "main")

        self.assertEqual(["stray"], out["local"])
        self.assertEqual([], out["remote"])

    def _render(self, **over):
        result = {
            "repo": "owner/repo",
            "project_dir": "/repo",
            "default_branch": "main",
            "fetch": {"ran": False, "ok": None},
            "pr_query_ok": True,
            "pr_query_limit": 20,
            "pr_query_truncated": False,
            "sync": {"branch": "main", "ahead": 0, "behind": 0, "fast_forward": True},
            "local_merged_branches": [],
            "local_branch_candidates": [],
            "unexplained_branches": {"local": [], "remote": []},
            "remote_branch_candidates": [],
            "closing_issue_candidates": [],
            "worktree_candidates": [],
            "untracked": [],
        }
        result.update(over)
        return merge_cleanup.render(result)

    def test_render_never_offers_a_delete_command_for_them(self):
        text = self._render(
            unexplained_branches={"local": ["review/local-only"], "remote": []}
        )

        self.assertIn("판단 필요", text)
        self.assertIn("review/local-only", text)
        # 이 부류는 되살릴 방법이 없다 — 삭제 명령을 제안하면 안 된다.
        self.assertNotIn("git branch -d review/local-only", text)
        self.assertNotIn("git branch -D review/local-only", text)
        self.assertNotIn("git push origin --delete", text)

    def test_render_blames_the_query_limit_only_when_it_was_actually_capped(self):
        capped = self._render(
            unexplained_branches={"local": [], "remote": ["old/forgotten"]},
            pr_query_truncated=True,
        )
        self.assertIn("--recent-limit", capped)

        full = self._render(
            unexplained_branches={"local": [], "remote": ["old/forgotten"]},
            pr_query_truncated=False,
        )
        # 전부 조회했으면 상한 탓을 하면 안 된다. PR 이 정말 없는 것이다.
        self.assertNotIn("--recent-limit", full)
        self.assertIn("PR 기록이 없다", full)

    def test_no_section_when_every_branch_is_accounted_for(self):
        """설명 안 되는 브랜치가 없으면 조회가 잘렸어도 조용해야 한다.

        PR 이 20건 넘는 저장소는 거의 항상 잘린다. 그때마다 경고를 띄우면 소음이라
        사람이 읽지 않게 된다. 잘림이 실제로 뭔가를 가렸을 때만 말한다.
        """
        text = self._render(pr_query_truncated=True)

        self.assertNotIn("판단 필요", text)
        self.assertNotIn("--recent-limit", text)

    def test_remote_branch_is_not_hidden_by_the_checked_out_branch_name(self):
        """체크아웃 중인 브랜치와 같은 이름의 원격 브랜치가 사라지면 안 된다.

        로컬에서 현재 브랜치를 빼는 이유는 git 이 삭제를 거부하기 때문인데, 원격에는
        그 사정이 없다. 같이 빼면 이 함수가 고치려는 것과 똑같이 조용히 사라진다.
        """
        with (
            patch.object(merge_cleanup, "_current_branch", return_value="feature/wip"),
            patch.object(
                merge_cleanup, "_local_branches", return_value={"main", "feature/wip"}
            ),
            patch.object(
                merge_cleanup,
                "_remote_branches",
                return_value={"main": "a", "feature/wip": "b"},
            ),
        ):
            out = merge_cleanup._unexplained_branches("/repo", [], [], "main")

        self.assertEqual([], out["local"], "현재 브랜치는 로컬에서 빠져야 한다")
        self.assertEqual(["feature/wip"], out["remote"], "원격에서는 빠지면 안 된다")
