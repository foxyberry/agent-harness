"""프로젝트가 주는 데이터를 **신뢰하지 않는지** 검사한다.

`.claude/memory/` 의 `routes.json` 과 그것이 가리키는 메모리 파일은 **설정이 아니라 사실상
실행 권한**이다. 훅은 편집·셸 명령마다 돌고, 그 내용을 모델 컨텍스트에 넣는다. 사용자가
클론한 남의 저장소일 수도 있다 — 그 저장소가 에이전트에게 말을 거는 통로가 된다.

여기서 지키는 것:

1. 주입 총량에 상한이 있다 (형제 훅 project-memory-index 와 같은 값)
2. 빈 문자열 규칙이 **모든** 명령·경로에 매칭되지 않는다
3. 주입 텍스트에 **출처 표시**가 있다 — 하네스 지시가 아니라 저장소가 준 자료라는
4. 커밋되면 안 되는 산출물을 **엔진이** 로컬 exclude 에 넣는다 (템플릿 복사에 기대지 않고)
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MEMORY_SEARCH = ROOT / "core" / "hooks" / "memory-search.py"

SPEC = importlib.util.spec_from_file_location(
    "pr_merge_reflect", ROOT / "core" / "hooks" / "pr-merge-reflect.py")
pr_merge_reflect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pr_merge_reflect)


class _Project(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = pathlib.Path(self._tmp.name)
        self.memory = self.project / ".claude" / "memory"
        self.memory.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def routes(self, rules):
        (self.memory / "routes.json").write_text(
            json.dumps({"rules": rules}), encoding="utf-8")

    def run_search(self, payload):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.project))
        env.pop("HARNESS_HOOK_TRACE", None)
        proc = subprocess.run(
            [sys.executable, str(MEMORY_SEARCH)], input=json.dumps(payload),
            capture_output=True, text=True, env=env, cwd=self.project, timeout=60)
        self.assertEqual(0, proc.returncode, proc.stderr)
        if not proc.stdout.strip():
            return ""
        return json.loads(proc.stdout)["additionalContext"]

    def bash(self, command="ls -la"):
        return {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                "tool_input": {"command": command}}


class InjectionBudgetTest(_Project):
    def test_a_huge_memory_file_cannot_flood_the_context(self):
        """상한이 없으면 저장소가 임의 길이 텍스트를 매 호출에 밀어 넣을 수 있다."""
        self.routes([{"command_contains": ["ls"], "memory": ["big.md"]}])
        (self.memory / "big.md").write_text("A" * 200_000, encoding="utf-8")

        out = self.run_search(self.bash())

        self.assertLess(len(out), 20_000,
                        f"주입이 {len(out)}자 — 상한이 안 걸렸다")
        # 무엇이 잘렸는지는 상황에 따라 다르지만(파일 하나가 넘쳤나 / 총량이 찼나),
        # **뭔가 빠졌다는 사실**은 항상 알려야 한다. 조용히 자르면 읽는 쪽이 전부라고 믿는다.
        self.assertIn("생략", out, "잘렸다는 사실을 알리지 않았다")

    def test_the_label_is_counted_too(self):
        """본문만 세면 파일 **이름**이 예산 밖에 남는다 — 빈 파일 수천 개로 우회할 수 있다.
        이름은 routes.json 이 정하므로 그것도 저장소가 통제하는 문자열이다."""
        names = [f"{'n' * 200}-{i}.md" for i in range(400)]
        self.routes([{"command_contains": ["ls"], "memory": names}])
        for name in names:
            (self.memory / name).write_text("", encoding="utf-8")   # 본문 0자

        out = self.run_search(self.bash())

        self.assertLess(len(out), 20_000,
                        f"주입이 {len(out)}자 — 라벨이 예산에 안 잡힌다")

    def test_many_files_share_one_budget(self):
        """파일당 상한이면 파일 수를 늘려 우회할 수 있다. 총량이어야 한다."""
        self.routes([{"command_contains": ["ls"],
                      "memory": [f"m{i}.md" for i in range(30)]}])
        for i in range(30):
            (self.memory / f"m{i}.md").write_text("B" * 5_000, encoding="utf-8")

        out = self.run_search(self.bash())

        self.assertLess(len(out), 20_000,
                        f"주입이 {len(out)}자 — 파일을 나누면 상한이 뚫린다")


class EmptyPatternTest(_Project):
    def test_empty_command_pattern_does_not_match_everything(self):
        """`"" in command` 는 항상 참이다. 규칙 하나로 모든 셸 명령에 주입이 걸린다."""
        self.routes([{"command_contains": [""], "memory": ["evil.md"]}])
        (self.memory / "evil.md").write_text("CANARY", encoding="utf-8")

        self.assertNotIn("CANARY", self.run_search(self.bash()))

    def test_empty_path_pattern_does_not_match_everything(self):
        self.routes([{"contains": [""], "memory": ["evil.md"]}])
        (self.memory / "evil.md").write_text("CANARY", encoding="utf-8")

        out = self.run_search({
            "hook_event_name": "PreToolUse", "tool_name": "Edit",
            "tool_input": {"file_path": "src/app.py", "new_string": "x"}})

        self.assertNotIn("CANARY", out)

    def test_a_real_pattern_still_matches(self):
        """빈 문자열만 걸러야 한다. 정상 규칙까지 죽이면 훅이 무용지물이다."""
        self.routes([{"command_contains": ["ls"], "memory": ["ok.md"]}])
        (self.memory / "ok.md").write_text("CANARY", encoding="utf-8")

        self.assertIn("CANARY", self.run_search(self.bash()))


class ProvenanceTest(_Project):
    def test_injected_text_says_where_it_came_from(self):
        """출처 표시가 없으면 모델은 저장소가 준 텍스트를 시스템 지시와 같은 무게로 읽는다."""
        self.routes([{"command_contains": ["ls"], "memory": ["m.md"]}])
        (self.memory / "m.md").write_text("규칙 본문", encoding="utf-8")

        out = self.run_search(self.bash())

        self.assertIn("저장소", out, "출처를 밝히지 않았다")
        self.assertIn("지시가 아님", out, "지시가 아니라는 표시가 없다")


class LocalExcludeTest(unittest.TestCase):
    """커밋되면 안 되는 산출물을 **엔진이** 막는지.

    보호가 project-template 에만 있으면, 템플릿을 복사하지 않은 사용자는 무방비다 —
    README 는 그 복사를 선택 단계로 안내한다.
    """

    def _git_project(self, tmp):
        project = pathlib.Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        return project

    def test_engine_excludes_drafts_and_rejection_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._git_project(tmp)
            pr_merge_reflect._ensure_local_cache_exclude(str(project))
            exclude = (project / ".git" / "info" / "exclude").read_text(encoding="utf-8")

        for entry in (".claude/.cache/",
                      ".claude/memory/_pending/",
                      ".claude/memory/_rejected.md"):
            with self.subTest(entry=entry):
                self.assertIn(entry, exclude)

    def test_the_paths_are_actually_ignored_by_git(self):
        """exclude 에 문자열이 들어간 것과 git 이 실제로 무시하는 건 다르다."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._git_project(tmp)
            pr_merge_reflect._ensure_local_cache_exclude(str(project))
            (project / ".claude" / "memory" / "_pending").mkdir(parents=True)
            (project / ".claude" / "memory" / "_pending" / "d.md").write_text("초안")
            (project / ".claude" / "memory" / "_rejected.md").write_text("폐기 기록")

            status = subprocess.run(["git", "status", "--porcelain"], cwd=project,
                                    capture_output=True, text=True).stdout

        self.assertNotIn("_pending", status, "회고 초안이 커밋 대상으로 잡힌다")
        self.assertNotIn("_rejected", status, "폐기 기록이 커밋 대상으로 잡힌다")

    def test_running_twice_does_not_duplicate_entries(self):
        """SessionStart 마다 돈다. 매번 추가하면 exclude 가 무한히 자란다."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._git_project(tmp)
            pr_merge_reflect._ensure_local_cache_exclude(str(project))
            pr_merge_reflect._ensure_local_cache_exclude(str(project))
            exclude = (project / ".git" / "info" / "exclude").read_text(encoding="utf-8")

        self.assertEqual(1, exclude.count(".claude/memory/_rejected.md"))


if __name__ == "__main__":
    unittest.main()
