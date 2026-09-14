#!/usr/bin/env python3
"""핸드오프가 **거짓으로 '커밋됨'** 이라고 말하지 않는가 (이슈 #133).

회귀 대상: `save` 는 커밋을 하지도 않으면서 본문에 "이 파일은 **커밋됨**" 을 박제했고,
`load` 는 파일 존재만 보고 "커밋된 핸드오프" 제목을 붙였다. untracked·staged·커밋 후 수정이
전부 "커밋됨" 으로 보였다.

지키는 불변식은 셋이다:
  1) 실제로 HEAD 와 내용이 같을 때만 '커밋됨' 이라고 말한다 (git 조회 실패는 '확인 불가').
  2) 저장된 본문에는 커밋 전후로 거짓이 되는 상태 주장을 쓰지 않는다.
  3) 안내하는 git 명령은 **실행 cwd 와 무관하게** 대상 저장소에서 돈다.

테스트는 진짜 임시 git 저장소 위에서 돈다. 반대로 바깥 세계(gh PR 조회 = 네트워크,
`~/.claude`·`~/.codex` = 사용자 세션 로그)는 전부 막는다 — 남의 로그를 열거나 네트워크를
타면 결과가 환경에 따라 흔들린다.
"""
import importlib.util
import os
import shlex
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

COMMITTED_CLAIMS = ("커밋됨", "커밋된 핸드오프")
LEGACY_BANNER = "> ⚠️ 이 파일은 **커밋됨**. 이어받는 사람/툴은 먼저 이걸 읽고"

FAKE_FACTS = {
    "branch": "fake",
    "status": "(없음)",
    "stat_unstaged": "(없음)",
    "stat_staged": "(없음)",
    "ahead": "(없음)",
    "pr": "(없음 또는 조회 불가)",
}


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True,
                   capture_output=True, text=True)


class _Args:
    """argparse.Namespace 대용 — cmd_save/cmd_load 가 읽는 속성만."""

    def __init__(self, **kw):
        self.project_dir = None
        self.agent = "claude"
        self.summary = self.done = self.next = self.verify = None
        self.deep = False
        self.transcript = None
        for k, v in kw.items():
            setattr(self, k, v)


class HandoffCommitStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)
        # repo 밖 cwd 겸 가짜 HOME. 실제 사용자 홈을 절대 건드리지 않게 한다.
        self.outside = tempfile.TemporaryDirectory()
        self.elsewhere = os.path.realpath(self.outside.name)
        _git(["init", "-b", "main"], self.repo)
        _git(["config", "user.email", "t@example.com"], self.repo)
        _git(["config", "user.name", "t"], self.repo)

    def tearDown(self):
        self.tmp.cleanup()
        self.outside.cleanup()

    def _run_cmd(self, fn, args):
        buf = StringIO()
        ctxs = [
            patch.dict(os.environ,
                       {"CLAUDE_PROJECT_DIR": self.repo, "HOME": self.elsewhere},
                       clear=True),
            patch.object(handoff, "git_facts", lambda root: dict(FAKE_FACTS)),
            patch.object(handoff, "transcript_hint", lambda root: []),
            patch("sys.stdout", buf),
        ]
        for c in ctxs:
            c.start()
        try:
            rc = fn(args)
        finally:
            for c in reversed(ctxs):
                c.stop()
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def _commit_something(self):
        Path(self.repo, "f.txt").write_text("hi\n")
        _git(["add", "."], self.repo)
        _git(["commit", "-m", "init"], self.repo)

    def _save(self, summary="요약"):
        return self._run_cmd(handoff.cmd_save, _Args(
            summary=summary, done="- 한 것", next="- 할 것", verify="테스트 통과"))

    def _load(self):
        return self._run_cmd(handoff.cmd_load, _Args())

    def _target(self):
        return handoff.handoff_path(self.repo, handoff.current_branch(self.repo))

    def _state(self):
        return handoff.handoff_sync_state(self.repo, self._target())

    def _rel(self):
        return os.path.relpath(self._target(), self.repo).replace(os.sep, "/")

    def _add(self):
        _git(["add", "--", self._rel()], self.repo)

    def _save_add_commit(self):
        self._save()
        self._add()
        _git(["commit", "-m", "handoff"], self.repo)

    def _write_handoff(self, body):
        """save 를 거치지 않고 파일을 직접 만든다 (예전 버전이 남긴 파일 재현용)."""
        path = self._target()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_text(body, encoding="utf-8")
        return path

    # ---------- 상태 판정 경계 ----------

    def test_missing_file(self):
        self._commit_something()
        self.assertEqual(self._state(), "missing")

    def test_untracked_after_save(self):
        """save 직후 — 커밋은커녕 `git add` 도 안 된 상태."""
        self._commit_something()
        self._save()
        self.assertEqual(self._state(), "untracked")

    def test_staged_new_is_not_committed(self):
        """`git add` 만 하면 tracked 이지만 **커밋은 아니다**. ls-files 로만 보면 놓친다."""
        self._commit_something()
        self._save()
        self._add()
        self.assertEqual(self._state(), "staged-new")

    def test_committed_clean(self):
        self._commit_something()
        self._save_add_commit()
        self.assertEqual(self._state(), "committed-clean")

    def test_committed_then_modified(self):
        """커밋 뒤 다시 save — 출력되는 본문은 HEAD 내용이 아니다."""
        self._commit_something()
        self._save_add_commit()
        self._save(summary="새 요약")
        self.assertEqual(self._state(), "committed-modified")

    def test_committed_then_modified_stays_modified_when_staged(self):
        """수정을 `git add` 해도 여전히 '커밋 후 수정됨'. staged 라고 HEAD 에 든 게 아니다."""
        self._commit_something()
        self._save_add_commit()
        self._save(summary="새 요약")
        self._add()
        self.assertEqual(self._state(), "committed-modified")

    def test_assume_unchanged_modification_is_still_modified(self):
        """`assume-unchanged` 는 `git diff` 를 속인다 — 그래서 내용을 직접 비교한다.

        diff 기반 판정이면 여기서 committed-clean 이 나와 #133 의 거짓 표시가 재발한다.
        """
        self._commit_something()
        self._save_add_commit()
        _git(["update-index", "--assume-unchanged", "--", self._rel()], self.repo)
        with open(self._target(), "a", encoding="utf-8") as f:
            f.write("\n손으로 덧붙인 줄 — HEAD 에는 없다\n")
        # 전제 확인: diff 는 정말로 '차이 없음' 이라고 말한다
        diff = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", self._rel()],
                              cwd=self.repo)
        self.assertEqual(diff.returncode, 0, "전제 실패: assume-unchanged 가 안 먹었다")
        self.assertEqual(self._state(), "committed-modified")

    def test_skip_worktree_modification_is_still_modified(self):
        self._commit_something()
        self._save_add_commit()
        _git(["update-index", "--skip-worktree", "--", self._rel()], self.repo)
        with open(self._target(), "a", encoding="utf-8") as f:
            f.write("\n또 다른 손수정\n")
        self.assertEqual(self._state(), "committed-modified")

    def test_removed_from_index_after_commit(self):
        """`git rm --cached` — HEAD 엔 있지만 지금 파일은 추적 밖."""
        self._commit_something()
        self._save_add_commit()
        _git(["rm", "--cached", "--", self._rel()], self.repo)
        self.assertEqual(self._state(), "committed-untracked")

    def test_unborn_head_is_not_committed(self):
        """커밋이 하나도 없는 새 저장소 — 'HEAD 조회 실패' 를 커밋됨으로 오인하면 안 된다.

        (cmd_save 는 unborn HEAD 를 DETACHED 로 보고 거부하므로 파일을 직접 만든다. 이 경로로
        들어오는 건 예전에 저장됐다 커밋 없이 옮겨온 파일 등이다.)
        """
        path = self._write_handoff("# 핸드오프\n")
        self.assertEqual(handoff.handoff_sync_state(self.repo, path), "untracked")
        _git(["add", "--", self._rel()], self.repo)
        self.assertEqual(handoff.handoff_sync_state(self.repo, path), "staged-new")

    def test_non_git_directory_is_unknown_not_committed(self):
        """git 저장소가 아닌 곳 — 모킹 없이 진짜 git 을 돌려서 unknown 이 나와야 한다."""
        path = os.path.join(self.elsewhere, handoff.HANDOFF_DIR, "x.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_text("# x\n", encoding="utf-8")
        self.assertEqual(handoff.handoff_sync_state(self.elsewhere, path), "unknown")

    def test_git_failure_is_unknown(self):
        """git 실행 자체가 실패하면 '확인 불가' — 절대 committed 로 떨어지지 않는다."""
        self._commit_something()
        self._save()
        with patch.object(handoff, "probe", lambda cmd, cwd=None: (None, False)):
            self.assertEqual(self._state(), "unknown")
        self.assertNotIn("커밋됨", handoff.handoff_state_label("unknown"))

    def test_abnormal_exit_is_unknown_not_absence(self):
        """조회가 128 로 죽는 건 '부재' 가 아니다 — `!= 0` 으로 뭉개면 안 된다.

        커밋까지 끝난 파일인데 ls-files 가 비정상 종료하면 답은 untracked 가 아니라 unknown.
        """
        self._commit_something()
        self._save_add_commit()
        self.assertEqual(self._state(), "committed-clean")
        real = handoff.probe

        def flaky(cmd, cwd=None):
            return (128, True) if "ls-files" in cmd else real(cmd, cwd=cwd)

        with patch.object(handoff, "probe", flaky):
            self.assertEqual(self._state(), "unknown")

    def test_line_ending_difference_is_reported_modified(self):
        """줄끝만 다른 파일을 `committed-modified` 라 부르는 건 **의도한 선택**이다.

        비교는 HEAD blob 과의 바이트 비교라 autocrlf 체크아웃·clean/smudge 필터가 걸리면
        내용이 같아도 modified 로 나온다. 여기서 정규화를 넣으면 CRLF 로 커밋된 blob 과
        LF 워킹트리가 같다고 나와, HEAD 에 없는 내용을 clean 이라 부르는 길이 열린다 —
        #133 이 바로 그 오류 방향이다. 의심하는 쪽으로 틀리는 게 맞다.
        """
        self._commit_something()
        self._save_add_commit()
        self.assertEqual(self._state(), "committed-clean")
        data = Path(self._target()).read_bytes()
        Path(self._target()).write_bytes(data.replace(b"\n", b"\r\n"))
        self.assertEqual(self._state(), "committed-modified")

    def test_head_blob_read_failure_is_unknown(self):
        """HEAD 내용을 못 꺼내면 같다고도 다르다고도 하지 않는다."""
        self._commit_something()
        self._save_add_commit()
        with patch.object(handoff, "head_blob", lambda root, rel: None):
            self.assertEqual(self._state(), "unknown")

    # ---------- 출력 ----------

    def test_load_labels_uncommitted_states_honestly(self):
        self._commit_something()
        self._save()
        out = self._load()
        self.assertIn("커밋 안 됨", out)
        # 출력 **전체**를 본다. 앞에서 '커밋 안 됨' 이라 보고해 놓고 뒤쪽 "깊은 복구" 줄에서
        # "커밋된 핸드오프로만 진행" 이라고 지시하면 같은 출력 안에서 모순이다.
        for claim in COMMITTED_CLAIMS:
            self.assertNotIn(claim, out, f"커밋 안 한 핸드오프에 '{claim}' 표기")

    def test_load_says_committed_only_when_head_matches(self):
        self._commit_something()
        self._save_add_commit()
        out = self._load()
        self.assertIn("커밋됨", out)
        self.assertIn("푸시 여부는 별개", out, "로컬 커밋을 원격 공유로 주장하면 안 된다")

        self._save(summary="새 요약")
        out2 = self._load()
        self.assertIn("커밋 후 수정됨", out2)
        self.assertIn("워킹트리", out2)

    def test_load_does_not_contradict_itself_when_clean(self):
        """committed-clean 인데 '커밋된 내용이 아님' 이라 덧붙이면 스스로와 모순이다.

        본문 줄이 말해야 하는 건 **출처**(워킹트리 파일을 읽었다)뿐이다.
        """
        self._commit_something()
        self._save_add_commit()
        out = self._load()
        self.assertIn("커밋됨 — HEAD 커밋 내용과 현재 파일이 동일", out)
        self.assertNotIn("HEAD 에 커밋된 내용이 아님", out)
        self.assertIn("워킹트리 파일을 읽은 내용", out, "출처는 계속 밝혀야 한다")

    def test_legacy_banner_does_not_win_over_real_state(self):
        """예전 버전이 본문에 박아둔 '이 파일은 **커밋됨**' 이 남아 있어도, 읽는 쪽이 그
        문장을 만나기 **전에** 실제 상태를 보게 해야 한다."""
        self._commit_something()
        self._write_handoff(
            "# 작업 핸드오프 — main\n\n" + LEGACY_BANNER + "\n\n## 요약\n옛날 파일\n")
        out = self._load()
        self.assertIn(LEGACY_BANNER, out, "본문은 그대로 보여준다 (검열하지 않는다)")
        self.assertIn("커밋 안 됨", out)
        self.assertLess(out.index("커밋 안 됨"), out.index(LEGACY_BANNER),
                        "실제 상태가 구버전 배너보다 먼저 나와야 한다")

    def test_load_missing_file_does_not_claim_commit(self):
        self._commit_something()
        out = self._load()
        self.assertIn("핸드오프 파일: 없음", out)
        for claim in COMMITTED_CLAIMS:
            self.assertNotIn(claim, out)

    def test_saved_body_has_no_commit_status_claim(self):
        """본문은 커밋 전후 어느 쪽에서도 거짓이 되면 안 된다 — 상태를 박제하지 않는다."""
        self._commit_something()
        self._save()
        body = Path(self._target()).read_text(encoding="utf-8")
        self.assertNotIn("이 파일은 **커밋됨**", body)
        self.assertNotIn("커밋 안 됨", body)

    def test_saved_body_has_no_absolute_path(self):
        """본문은 머신을 넘어 이식되는 정본 — 이 머신의 절대경로를 넣으면 안 된다."""
        self._commit_something()
        self._save()
        self.assertNotIn(self.repo, Path(self._target()).read_text(encoding="utf-8"))

    def test_saved_body_keeps_narrative_sections(self):
        """상태 배너를 고치면서 사람이 쓴 서술 섹션을 잃지 않는다."""
        self._commit_something()
        self._save(summary="이번 요약")
        body = Path(self._target()).read_text(encoding="utf-8")
        for chunk in ("## 요약", "이번 요약", "## 완료한 것", "- 한 것",
                      "## 남은 것 / 다음 액션", "- 할 것", "## 검증 상태", "테스트 통과"):
            self.assertIn(chunk, body)

    def test_save_prints_command_that_runs_from_any_cwd(self):
        """안내한 명령을 **repo 밖 cwd 에서** 그대로 붙여넣어도 대상 저장소에 먹혀야 한다.

        `--project-dir` 나 Codex 스킬 폴더 실행처럼 cwd ≠ 대상 저장소인 경우가 정상 경로다.
        셸 메타문자가 있는 브랜치에서도 인용이 깨지지 않는지 같이 본다.
        """
        self._commit_something()
        _git(["checkout", "-b", "fix/it's-$weird"], self.repo)
        lines = self._save().splitlines()

        add = shlex.split(next(l for l in lines if " add -- " in l).strip())
        self.assertEqual(add[:5], ["git", "-C", self.repo, "add", "--"])
        self.assertEqual(add[5], self._rel())

        # 실제로 먹히는지까지 확인 — repo 밖에서 실행한다 (인용·-C 가 깨졌으면 여기서 죽는다)
        done = subprocess.run(add, cwd=self.elsewhere, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self._state(), "staged-new")

        commit = next(l for l in lines if " commit" in l).strip()
        self.assertEqual(shlex.split(commit.split("#")[0])[:4],
                         ["git", "-C", self.repo, "commit"])

    def test_save_reports_current_state(self):
        self._commit_something()
        self.assertIn("현재 git 상태: 커밋 안 됨", self._save())


if __name__ == "__main__":
    unittest.main()
