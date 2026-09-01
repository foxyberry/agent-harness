"""회고 skip rule 이 **회고 산출물 PR** 을 실제로 걸러내는지 고정한다 (이슈 #130).

#36 이 skip rule 을 넣었지만 두 구멍이 있었다.

1. 기본 skip 경로가 `.claude/memory/**` 계열뿐이었다. 교훈을 **규칙으로 승격**하는 자리
   (`CLAUDE.md`·`AGENTS.md`·`.claude/agents/**`·`.claude/skills/**`)는 안 담겼다.
2. 판정이 `all()` 이라 **파일 하나면 무력화**됐다. `.gitignore` 한 줄 같은 부수 변경이
   섞이면 skip 이 풀린다.

결과는 루프였다. 회고로 만든 PR 이 머지되면 그 PR 의 회고를 다시 요구하고, 그 산출물이
또 머지되면 또 요구한다. 새로 나올 교훈이 없는데도 사람이 매번 끊어줘야 했다.

여기 고정하는 것은 두 방향이다 — **회고 산출물은 걸러지고, 실제 작업은 안 걸러진다.**
후자를 같이 고정하는 이유는 skip 을 넓히다 보면 진짜 작업 회고까지 삼키기 때문이다.
그건 조용히 일어나서(경고도 실패도 없다) 테스트 말고는 잡을 방법이 없다.
"""
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "pr_merge_reflect", ROOT / "core" / "hooks" / "pr-merge-reflect.py")
prm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prm)


def _skip(files, project_dir="."):
    """실제 `_should_skip_reflect` 를 부른다. PR 조회만 가짜로 준다.

    ⚠️ 판정 로직을 여기 베껴 쓰면 안 된다. 처음엔 그렇게 짰는데, 프로덕션의 필터를
    지우는 변이를 **테스트가 못 잡았다** — 사본을 시험하고 있었기 때문이다. 가짜로
    돌리는 건 네트워크(`gh`)뿐이고, 규칙은 언제나 본체 것을 쓴다.
    """
    details = {"labels": [], "commit_messages": [], "files": list(files)}
    with patch.object(prm, "_pr_details", return_value=details):
        return prm._should_skip_reflect(project_dir, 1)


class ReflectSkipScopeTest(unittest.TestCase):
    # --- 걸러져야 하는 것: 회고 산출물 ---

    def test_the_reported_loop_case_is_skipped(self):
        """이슈 #130 이 보고한 PR 그대로. 이게 이 파일의 회귀 케이스다."""
        files = [".claude/memory/lesson.md", ".claude/memory/INDEX.md",
                 "CLAUDE.md", ".claude/agents/qa-engineer.md", ".gitignore"]
        self.assertTrue(_skip(files),
                        "회고 산출물 PR 인데 회고를 다시 요구한다 — 루프가 재발한다")

    def test_memory_only_pr_stays_skipped(self):
        """#36 이 이미 걸러내던 모양. 넓히다 좁아지지 않았는지 확인한다."""
        files = [".claude/memory/INDEX.md", ".claude/memory/routes.json",
                 ".claude/memory/a.md", ".claude/memory/b.md"]
        self.assertTrue(_skip(files))

    def test_lesson_promoted_to_a_rule_file_is_skipped(self):
        for files in ([("AGENTS.md")], ["CLAUDE.md"], ["project-template/AGENTS.md"],
                      [".claude/skills/foo/SKILL.md"], [".claude/agents/reviewer.md"]):
            with self.subTest(files=files):
                self.assertTrue(_skip(list(files)))

    def test_incidental_file_does_not_break_the_verdict(self):
        """`.gitignore` 한 줄이 회고 산출물을 작업 PR 로 만들지 않는다."""
        base = [".claude/memory/lesson.md"]
        for extra in (".gitignore", ".gitattributes", "docs/.gitignore"):
            with self.subTest(extra=extra):
                self.assertTrue(_skip(base + [extra]))

    # --- 걸러지면 안 되는 것: 실제 작업 ---

    def test_real_work_is_still_reflected(self):
        """#129(문서+테스트)처럼 진짜 작업은 회고 대상으로 남아야 한다."""
        files = ["README.md", "docs/guide.md", "tests/test_doc_link_coverage.py"]
        self.assertFalse(_skip(files),
                         "실제 작업 회고를 삼키면 조용히 사라진다 — 경고도 실패도 없다")

    def test_code_mixed_with_memory_is_still_reflected(self):
        files = ["core/hooks/reflect.py", ".claude/memory/x.md"]
        self.assertFalse(_skip(files))

    def test_only_incidental_files_is_not_a_skip(self):
        """부수 파일만 남으면 판단 근거가 없다 — fail-open(회고한다)."""
        self.assertFalse(_skip([".gitignore"]))

    def test_empty_file_list_is_not_a_skip(self):
        self.assertFalse(_skip([]))


class ReflectSkipConfigTest(unittest.TestCase):
    """프로젝트 설정이 새 키를 다룰 수 있는지 — 키를 늘릴 때 같이 안 늘면 조용히 뒤처진다."""

    def _cfg(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp, ".claude", "memory")
            d.mkdir(parents=True)
            (d / "reflect-skip.json").write_text(json.dumps(data), encoding="utf-8")
            return prm._load_reflect_skip_config(tmp)

    def test_project_can_extend_ignore_paths(self):
        cfg = self._cfg({"ignore_paths": ["*.lock"]})
        self.assertIn("*.lock", cfg["ignore_paths"])
        self.assertIn(".gitignore", cfg["ignore_paths"], "기본값이 사라지면 안 된다")

    def test_defaults_false_clears_every_key_without_raising(self):
        """`defaults: false` 가 키를 하나라도 빠뜨리면 그 키를 읽는 순간 KeyError 다."""
        cfg = self._cfg({"defaults": False, "paths": ["only/**"]})
        self.assertEqual(["only/**"], cfg["paths"])
        for key in prm.DEFAULT_REFLECT_SKIP:
            with self.subTest(key=key):
                self.assertIn(key, cfg)

    def test_every_default_key_is_extendable(self):
        """기본값에 키를 추가했는데 확장 루프에 안 넣으면 사용자가 못 늘린다."""
        probe = {k: ["zz-probe"] for k in prm.DEFAULT_REFLECT_SKIP}
        cfg = self._cfg(probe)
        for key in prm.DEFAULT_REFLECT_SKIP:
            with self.subTest(key=key):
                self.assertIn("zz-probe", cfg[key])


if __name__ == "__main__":
    unittest.main()
