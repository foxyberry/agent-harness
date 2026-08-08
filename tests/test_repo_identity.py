#!/usr/bin/env python3
"""repo_identity: 프로젝트 폴더 **밖**의 worktree 도 같은 저장소로 인식하는가.

회귀 대상: 경로 prefix(`cwd.startswith(project_dir + os.sep)`) 판정 때문에 외부 worktree 의
세션이 통째로 누락됐다(이슈 #75). 아래 test_sibling_worktree_belongs 가 그 재현이다.
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

    # ---------- 핵심 회귀 ----------

    def test_sibling_worktree_belongs(self):
        """프로젝트 폴더의 **형제** 경로에 있는 worktree 도 같은 저장소로 인식한다.

        경로 prefix 판정에서는 반드시 탈락하던 케이스 — 이슈 #75 의 실제 상황
        (`Repository/.agent-worktrees/...` vs `Repository/agent-harness`)."""
        wt = self._add_worktree(os.path.join(self.base, "wt-sibling"), "feat-a")
        m = ProjectMatcher(self.repo)
        self.assertFalse(wt.startswith(self.repo + os.sep),
                         "전제: worktree 가 프로젝트 하위가 아니어야 이 테스트가 의미 있다")
        self.assertTrue(m.belongs(wt))

    def test_far_away_worktree_belongs(self):
        """완전히 다른 트리(Codex Desktop 의 `~/.codex/worktrees/<hash>` 상당)도 인식."""
        far = os.path.join(self.base, "elsewhere", "deadbeef")
        os.makedirs(os.path.dirname(far))
        wt = self._add_worktree(far, "feat-b")
        self.assertTrue(ProjectMatcher(self.repo).belongs(wt))

    def test_subdir_of_worktree_belongs(self):
        """worktree 안의 하위 디렉터리에서 돈 세션도 인식(에이전트가 cd 해서 작업)."""
        wt = self._add_worktree(os.path.join(self.base, "wt-sub"), "feat-c")
        sub = os.path.join(wt, "nested")
        os.makedirs(sub)
        self.assertTrue(ProjectMatcher(self.repo).belongs(sub))

    def test_project_dir_itself_belongs(self):
        self.assertTrue(ProjectMatcher(self.repo).belongs(self.repo))

    # ---------- 남의 저장소는 배제 ----------

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
        """`myrepo-evil` 은 `myrepo` 의 하위가 아니다 — startswith 오탐 방지."""
        evil = self.repo + "-evil"
        os.makedirs(evil)
        _git(["init", "-b", "main"], evil)
        self.assertFalse(ProjectMatcher(self.repo).belongs(evil))

    # ---------- 제거된 worktree: alias 캐시 ----------

    def test_removed_worktree_resolved_via_alias(self):
        """관측된 뒤 제거된 worktree 는 alias 캐시로 되짚는다.

        경로가 사라지면 git 에 물어볼 수 없다 — 관측 기록이 유일한 근거."""
        wt = self._add_worktree(os.path.join(self.base, "wt-gone"), "feat-d")
        m1 = ProjectMatcher(self.repo)
        self.assertTrue(m1.record_worktrees(), "관측 기록이 저장돼야 한다")

        _git(["worktree", "remove", "--force", wt], self.repo)
        self.assertFalse(os.path.exists(wt))

        m2 = ProjectMatcher(self.repo)  # 캐시를 디스크에서 새로 읽는 인스턴스
        self.assertTrue(m2.belongs(wt))

    def test_unobserved_removed_worktree_not_guessed(self):
        """한 번도 관측 안 된 채 사라진 경로는 추정하지 않는다(오탐 방지)."""
        ghost = os.path.join(self.base, "never-seen")
        m = ProjectMatcher(self.repo)
        m.record_worktrees()
        self.assertFalse(m.belongs(ghost))

    def test_alias_cache_lives_in_git_common_dir(self):
        """alias 는 git 공통 디렉터리 안 — 커밋되지 않고, 모든 worktree 가 공유한다."""
        m = ProjectMatcher(self.repo)
        m.record_worktrees()
        expected = os.path.join(git_common_dir(self.repo), "agent-harness", "worktree-alias.json")
        self.assertTrue(os.path.exists(expected))

    def test_alias_shared_between_worktree_and_main(self):
        """linked worktree 에서 관측한 기록을 **본체 체크아웃**이 읽는다.

        캐시를 project_dir 아래 두면 깨지는 케이스: worktree 에서 관측 → 그 worktree 를
        제거 → 캐시도 함께 사라져 본체는 아무것도 못 되짚는다."""
        wt = self._add_worktree(os.path.join(self.base, "wt-observer"), "feat-e")
        gone = self._add_worktree(os.path.join(self.base, "wt-doomed"), "feat-f")

        # 관측 주체 = linked worktree (본체가 아니다)
        ProjectMatcher(wt).record_worktrees()

        _git(["worktree", "remove", "--force", gone], self.repo)
        self.assertFalse(os.path.exists(gone))

        # 본체 체크아웃에서 조회 — 같은 캐시를 봐야 한다
        self.assertTrue(ProjectMatcher(self.repo).belongs(gone))

    def test_alias_survives_observing_worktree_removal(self):
        """관측을 수행한 worktree 자체가 지워져도 기록은 남는다(캐시가 그 안에 없으므로)."""
        wt = self._add_worktree(os.path.join(self.base, "wt-selfgone"), "feat-g")
        ProjectMatcher(wt).record_worktrees()
        _git(["worktree", "remove", "--force", wt], self.repo)
        self.assertTrue(ProjectMatcher(self.repo).belongs(wt))

    # ---------- 하위 유틸 ----------

    def test_worktree_roots_includes_all(self):
        a = self._add_worktree(os.path.join(self.base, "wt-1"), "b1")
        b = self._add_worktree(os.path.join(self.base, "wt-2"), "b2")
        roots = worktree_roots(self.repo)
        self.assertIn(os.path.normcase(a), [os.path.normcase(r) for r in roots])
        self.assertIn(os.path.normcase(b), [os.path.normcase(r) for r in roots])

    def test_worktree_path_with_space(self):
        """porcelain 경로에 공백이 있어도 파싱된다 — split() 이면 깨지는 케이스."""
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
        """fw/history 경로도 관측을 남긴다.

        자동 회고는 기본 꺼짐이라, 그쪽에만 기록을 맡기면 캐시가 영영 안 생긴다 —
        회고를 안 켠 사용자는 worktree 제거 후 되짚기가 통째로 불가능해진다."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "core", "scripts"))
        import handoff

        gone = self._add_worktree(os.path.join(self.base, "wt-fw"), "feat-h")
        handoff._project_matcher(self.repo)          # fw/history 가 하는 일
        _git(["worktree", "remove", "--force", gone], self.repo)

        self.assertTrue(ProjectMatcher(self.repo).belongs(gone))

    def test_is_within(self):
        self.assertTrue(_is_within("/a/b/c", "/a/b"))
        self.assertFalse(_is_within("/a/bc", "/a/b"))   # prefix 오탐
        self.assertFalse(_is_within("/a/b", "/a/b"))    # 자기 자신은 하위가 아님
        self.assertFalse(_is_within("/a/b", "/x/y"))


if __name__ == "__main__":
    unittest.main()
