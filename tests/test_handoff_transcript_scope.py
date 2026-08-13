"""세션 로그 탐색이 **현재 프로젝트**로 스코프되는지 고정한다 (이슈 #95).

사고 재현: 프로젝트 A 에서 이어받기를 했는데, 전역 mtime 이 더 최신인 프로젝트 B 의
세션이 "직전 작업"으로 보고됐다. 원인은 스코핑 부재가 아니라 **스코핑된 선택기에
도달하지 못한 것**이었다 —
  - `load --deep` 이 Codex 쪽 요약을 아예 호출하지 않았고,
  - 힌트는 `~/.codex/sessions` 를 전역으로 훑어 "존재함"만 알렸다.
그래서 사람·모델이 로그를 직접 뒤졌고, 손 탐색에는 스코핑이 없었다.

여기서 고정하는 것은 "여러 프로젝트 로그가 섞여 있어도 내 프로젝트 것만 고른다" 와
"못 찾으면 없다고 분명히 말한다" 두 가지다.
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "core" / "scripts" / "handoff.py"
SPEC = importlib.util.spec_from_file_location("handoff", SCRIPT)
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)


def _git_init(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return str(path.resolve())


def _write_rollout(home, name, sid, cwd, mtime):
    """~/.codex/sessions/<날짜 트리>/rollout-*.jsonl 하나를 만든다."""
    p = pathlib.Path(home, ".codex", "sessions", "2026", "08", "11", name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": sid, "cwd": cwd}}) + "\n"
        + json.dumps({"type": "message", "role": "user", "content": "직전 작업 내용"}) + "\n",
        encoding="utf-8",
    )
    os.utime(p, (mtime, mtime))
    return p


def _write_claude_transcript(home, project_dir, stem, mtime):
    key = project_dir.replace("/", "-").replace(".", "-")
    p = pathlib.Path(home, ".claude", "projects", key, f"{stem}.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "직전 작업"}}) + "\n",
        encoding="utf-8",
    )
    os.utime(p, (mtime, mtime))
    return p


class _TwoProjects(unittest.TestCase):
    """프로젝트 A(내 것)와 B(남의 것). B 로그가 항상 더 최신이다."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self._tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        self.a = _git_init(base / "proj-a")
        self.b = _git_init(base / "proj-b")
        # B 를 더 최신으로 — 전역 mtime 정렬이면 B 가 이긴다.
        self.now = 1_785_000_000.0
        self._env = dict(os.environ)
        os.environ["HOME"] = str(self.home)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()


class CodexRolloutScopeTest(_TwoProjects):
    def test_newer_other_project_rollout_is_not_returned(self):
        _write_rollout(self.home, "rollout-a.jsonl", "sid-a", self.a, self.now - 3600)
        _write_rollout(self.home, "rollout-b.jsonl", "sid-b", self.b, self.now)

        rows = handoff._recent_codex_rollouts(self.a, limit=10)

        self.assertEqual(
            ["rollout-a.jsonl"], [os.path.basename(r[2]) for r in rows],
            "전역 mtime 이 더 최신인 다른 프로젝트 rollout 이 섞이면 안 된다",
        )

    def test_subdirectory_cwd_still_belongs_to_project(self):
        sub = pathlib.Path(self.a, "src", "deep")
        sub.mkdir(parents=True)
        _write_rollout(self.home, "rollout-sub.jsonl", "sid-sub", str(sub), self.now)

        rows = handoff._recent_codex_rollouts(self.a, limit=10)

        self.assertEqual(["rollout-sub.jsonl"], [os.path.basename(r[2]) for r in rows])


class TranscriptHintTest(_TwoProjects):
    def test_no_codex_hint_when_only_other_project_has_rollouts(self):
        _write_rollout(self.home, "rollout-b.jsonl", "sid-b", self.b, self.now)

        hints = handoff.transcript_hint(self.a)

        self.assertEqual(
            [], [h for h in hints if "Codex" in h],
            "다른 프로젝트 rollout 만 있을 때 '존재함' 힌트를 내면 손 탐색을 부른다",
        )

    def test_codex_hint_present_for_own_rollout(self):
        _write_rollout(self.home, "rollout-a.jsonl", "sid-a", self.a, self.now)

        hints = handoff.transcript_hint(self.a)

        self.assertTrue([h for h in hints if "Codex rollout 있음" in h])

    def test_hint_stops_reading_once_a_match_is_found(self):
        """힌트는 평범한 `load` 마다 돈다. 전체 스캔을 물리면 안 된다.

        내 프로젝트 세션이 최신이면 그 하나만 읽고 끝나야 한다 — 뒤에 남의 프로젝트
        rollout 이 아무리 많아도 열지 않는다.
        """
        # A 가 가장 최신이어야 한다 — 아래 "1개만 열었다" 단언이 이 순서에 기댄다.
        _write_rollout(self.home, "rollout-a.jsonl", "sid-a", self.a, self.now)
        for i in range(20):
            _write_rollout(self.home, f"rollout-b{i}.jsonl", f"sid-b{i}", self.b, self.now - 100 - i)

        opened = []
        real = handoff._codex_rollout_meta

        def counting_meta(path):
            opened.append(path)
            return real(path)

        handoff._codex_rollout_meta = counting_meta
        try:
            self.assertTrue(handoff._has_project_codex_rollout(self.a))
        finally:
            handoff._codex_rollout_meta = real

        self.assertEqual(
            1, len(opened),
            f"최신 매칭 하나에서 멈춰야 하는데 {len(opened)}개를 열었다",
        )

    def test_hint_names_only_commands_that_exist(self):
        _write_claude_transcript(self.home, self.a, "sess-a", self.now)
        _write_rollout(self.home, "rollout-a.jsonl", "sid-a", self.a, self.now)

        joined = "\n".join(handoff.transcript_hint(self.a))

        # 없는 명령을 안내하면 사용자가 쳐도 아무 일이 안 일어나고, 결국 손으로 찾게 된다.
        for dead in ("/fw-claude", "/continue-claude"):
            self.assertNotIn(dead, joined)
        self.assertIn("/fw-both", joined)


class LoadDeepTest(_TwoProjects):
    def _run_load_deep(self, project_dir):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        proc = subprocess.run(
            ["python3", str(SCRIPT), "load", "--deep", "--project-dir", project_dir],
            capture_output=True, text=True, env=env, cwd=project_dir,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        return proc.stdout

    def test_deep_summarizes_this_projects_codex_session(self):
        _write_rollout(self.home, "rollout-a.jsonl", "sid-a", self.a, self.now - 3600)
        _write_rollout(self.home, "rollout-b.jsonl", "sid-b", self.b, self.now)

        out = self._run_load_deep(self.a)

        # Codex 요약 자체가 나와야 한다 — 예전엔 Claude 만 요약하고 여기서 끝났다.
        self.assertIn("Codex rollout", out)
        self.assertIn("rollout-a.jsonl", out)
        self.assertNotIn("rollout-b.jsonl", out)

    def test_deep_says_none_instead_of_pointing_at_other_projects(self):
        _write_rollout(self.home, "rollout-b.jsonl", "sid-b", self.b, self.now)

        out = self._run_load_deep(self.a)

        self.assertIn("이 프로젝트의 최근 세션 로그 없음", out)
        self.assertNotIn("rollout-b.jsonl", out)


class TargetDisclosureTest(_TwoProjects):
    """어느 프로젝트를 봤는지 출력에 드러나야 한다.

    대상을 잘못 지목하는 것 자체는 툴의 결함이 아니다 — 시킨 대로 한 것이다. 결함은
    **틀렸다는 걸 알아챌 방법이 없는 것**이다. 지금까지 출력에는 브랜치명만 있어서,
    엉뚱한 저장소를 가리켜도 그 저장소의 브랜치와 세션이 멀쩡하게 나왔다.
    """

    def _run(self, *argv):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env.pop("CLAUDE_PROJECT_DIR", None)
        proc = subprocess.run(
            ["python3", str(SCRIPT), *argv],
            capture_output=True, text=True, env=env, cwd=self.a,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        return proc.stdout

    def test_load_shows_resolved_root_and_why(self):
        out = self._run("load", "--project-dir", self.b)

        self.assertIn(self.b, out, "지목한 프로젝트 루트가 출력에 없으면 오지목을 못 알아챈다")
        self.assertIn("--project-dir", out, "왜 그 루트로 정했는지도 밝혀야 한다")

    def test_fw_shows_resolved_root(self):
        out = self._run("fw", "--from", "claude", "--project-dir", self.b)

        self.assertIn(self.b, out)

    def test_root_source_says_cwd_when_not_given(self):
        out = self._run("load")

        self.assertIn(self.a, out)
        self.assertIn("현재 디렉터리", out)

    def test_history_names_project_even_with_no_results(self):
        # 결과가 없을 때야말로 "대상을 잘못 골랐나" 와 "정말 없나" 가 구분돼야 한다.
        out = self._run("history", "--project-dir", self.b)

        self.assertIn(self.b, out)


if __name__ == "__main__":
    unittest.main()
