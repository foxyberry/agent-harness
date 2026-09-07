"""회고 skip rule 이 **회고 산출물 PR** 을 걸러내는지 고정한다 (이슈 #130).

#36 이 skip rule 을 넣었지만 두 구멍이 있었다.

1. skip 경로가 `.claude/memory/**` 계열뿐이라, 교훈을 **규칙으로 승격**한 PR
   (`CLAUDE.md`·`AGENTS.md`·`.claude/agents/**`)이 안 걸렸다.
2. 판정이 `all()` 이라 **파일 하나면 무력화**됐다. `.gitignore` 한 줄이면 skip 이 풀린다.

결과는 루프였다 — 회고로 만든 PR 이 그 PR 의 회고를 다시 요구한다.

## 엔진과 데이터를 갈라서 본다

고칠 때 첫 시도는 넓은 목록을 **엔진 기본값**에 넣는 것이었다. Codex 리뷰와 자체 점검이
같은 문제를 양쪽에서 찾았다: 그러면 진짜 규칙 변경·`.gitignore` 정책 변경 회고가 **조용히**
사라진다. 루프보다 알아채기 어렵다.

`AGENTS.md` 의 원칙이 이미 답이었다 — 엔진은 generic, "무엇을" 은 프로젝트 데이터.
`.claude/memory/**` 는 하네스가 자기가 만드는 경로라 엔진이 알아도 되지만, `CLAUDE.md` 나
`.gitignore` 는 **그 프로젝트의 파일**이고 회고할 값어치가 프로젝트마다 다르다.

그래서 두 층을 **따로** 고정한다:

- `EngineDefaultsTest` — 엔진 기본값은 하네스 산출물만 안다. 프로젝트 파일은 모른다.
- `TemplateDataTest` — 템플릿 데이터를 깐 프로젝트에서 보고된 케이스가 실제로 막힌다.

섞어서 보면 둘 중 어느 쪽이 일하는지 알 수 없고, 나중에 기본값이 슬그머니 넓어져도
테스트가 통과한다.
"""
import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "project-template" / ".claude" / "memory" / "reflect-skip.json"
SPEC = importlib.util.spec_from_file_location(
    "pr_merge_reflect", ROOT / "core" / "hooks" / "pr-merge-reflect.py")
prm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prm)


def _skip(files, project_dir):
    """실제 `_should_skip_reflect` 를 부른다. PR 조회(`gh`)만 가짜로 준다.

    ⚠️ 판정 로직을 여기 베껴 쓰면 안 된다. 처음엔 그렇게 짰는데, 프로덕션의 필터를 지우는
    변이를 **테스트가 못 잡았다** — 사본을 시험하고 있었기 때문이다. 가짜로 돌리는 건
    네트워크뿐이고, 규칙은 언제나 본체 것을 쓴다.
    """
    details = {"labels": [], "commit_messages": [], "files": list(files)}
    with patch.object(prm, "_pr_details", return_value=details):
        return prm._should_skip_reflect(project_dir, 1)


class _Project(unittest.TestCase):
    """설정 파일이 없는 빈 프로젝트. 있으면 `skip_config` 를 채운다."""

    skip_config = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        if self.skip_config is not None:
            d = pathlib.Path(self.dir, ".claude", "memory")
            d.mkdir(parents=True)
            shutil.copy(self.skip_config, d / "reflect-skip.json")

    def tearDown(self):
        self._tmp.cleanup()

    def skip(self, files):
        return _skip(files, self.dir)


class EngineDefaultsTest(_Project):
    """설정 데이터가 없을 때. 엔진은 **하네스 산출물만** 안다."""

    def test_harness_output_is_skipped(self):
        for files in ([".claude/memory/lesson.md", ".claude/memory/INDEX.md"],
                      [".claude/handoff/main.md"],
                      [".agents/skills/fw/SKILL.md"]):
            with self.subTest(files=files):
                self.assertTrue(self.skip(files))

    def test_engine_does_not_decide_about_project_files(self):
        """`CLAUDE.md`·`AGENTS.md` 는 프로젝트 파일이다 — 엔진이 회고 여부를 정하지 않는다.

        이 저장소가 그 예다. #105 는 `AGENTS.md` 로 하네스 범위를 좁힌 큰 결정이었고
        회고할 값어치가 있었다. 다른 팀에선 같은 파일이 보일러플레이트일 수 있다.
        """
        for files in (["AGENTS.md"], ["CLAUDE.md"], [".claude/agents/reviewer.md"],
                      [".claude/skills/foo/SKILL.md"]):
            with self.subTest(files=files):
                self.assertFalse(self.skip(files),
                                 "엔진 기본값이 프로젝트 파일까지 삼키고 있다")

    def test_engine_ships_no_ignore_list(self):
        """메커니즘은 있고 목록은 비어 있다 — 무엇을 부수로 볼지는 프로젝트가 정한다."""
        self.assertIn("ignore_paths", prm.DEFAULT_REFLECT_SKIP)
        self.assertEqual([], prm.DEFAULT_REFLECT_SKIP["ignore_paths"])
        self.assertFalse(self.skip([".claude/memory/x.md", ".gitignore"]),
                         "데이터 없이 엔진이 .gitignore 를 부수로 단정하면 안 된다")

    def test_real_work_is_reflected(self):
        self.assertFalse(self.skip(["README.md", "docs/guide.md", "tests/t.py"]))

    def test_code_mixed_with_memory_is_reflected(self):
        self.assertFalse(self.skip(["core/hooks/reflect.py", ".claude/memory/x.md"]))

    def test_empty_file_list_is_not_a_skip(self):
        self.assertFalse(self.skip([]))


class TemplateDataTest(_Project):
    """템플릿 데이터를 깐 프로젝트. 보고된 루프가 여기서 막힌다."""

    skip_config = TEMPLATE

    def test_the_reported_loop_case_is_skipped(self):
        """이슈 #130 이 보고한 PR 그대로. 이 파일의 회귀 케이스다."""
        files = [".claude/memory/lesson.md", ".claude/memory/INDEX.md",
                 "CLAUDE.md", ".claude/agents/qa-engineer.md", ".gitignore"]
        self.assertTrue(self.skip(files),
                        "회고 산출물 PR 인데 회고를 다시 요구한다 — 루프가 재발한다")

    def test_lesson_promoted_to_a_rule_file_is_skipped(self):
        for files in (["AGENTS.md"], ["CLAUDE.md"], ["project-template/AGENTS.md"],
                      [".claude/skills/foo/SKILL.md"], [".claude/agents/reviewer.md"]):
            with self.subTest(files=files):
                self.assertTrue(self.skip(files))

    def test_incidental_file_does_not_break_the_verdict(self):
        base = [".claude/memory/lesson.md"]
        for extra in (".gitignore", ".gitattributes", "docs/.gitignore"):
            with self.subTest(extra=extra):
                self.assertTrue(self.skip(base + [extra]))

    def test_real_work_is_still_reflected(self):
        """넓힌 데이터를 깔아도 진짜 작업은 회고 대상으로 남는다.

        이쪽이 더 중요하다 — skip 이 과해지면 회고가 경고도 실패도 없이 사라진다.
        """
        self.assertFalse(self.skip(["README.md", "docs/guide.md", "tests/t.py"]))

    def test_code_mixed_with_rules_is_still_reflected(self):
        self.assertFalse(self.skip(["core/hooks/reflect.py", "AGENTS.md"]))

    def test_only_incidental_files_is_not_a_skip(self):
        """부수 파일만 남으면 판단 근거가 없다 — fail-open(회고한다)."""
        self.assertFalse(self.skip([".gitignore"]))


class ReflectSkipConfigTest(unittest.TestCase):
    """설정 로더가 새 키를 다루는지 — 키를 늘릴 때 같이 안 늘면 조용히 뒤처진다."""

    def _cfg(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp, ".claude", "memory")
            d.mkdir(parents=True)
            (d / "reflect-skip.json").write_text(json.dumps(data), encoding="utf-8")
            return prm._load_reflect_skip_config(tmp)

    def test_project_can_fill_ignore_paths(self):
        cfg = self._cfg({"ignore_paths": ["*.lock"]})
        self.assertIn("*.lock", cfg["ignore_paths"])

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

    def test_shipped_template_parses_and_covers_both_layers(self):
        """템플릿이 실제로 로드되는지 — 문법이 깨지면 조용히 무시된다(except: return cfg)."""
        cfg = prm._load_reflect_skip_config(str(TEMPLATE.parents[2]))
        self.assertIn("AGENTS.md", cfg["paths"])
        self.assertIn(".gitignore", cfg["ignore_paths"])


if __name__ == "__main__":
    unittest.main()
