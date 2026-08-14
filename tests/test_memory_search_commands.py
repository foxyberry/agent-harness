"""memory-search 가 셸 명령에도 걸리는지, 그리고 **조용해야 할 때 조용한지** (이슈 #90).

배경: 규칙이 문서에 있어도 필요한 순간에 안 닿으면 안 지켜진다. "PR 만들기 전에 리뷰 결과를
댓글로 남겨라" 는 파일 편집과 무관해서, 편집 시점에만 뜨는 memory-search 로는 절대 닿지 않았다.

그래서 `Bash` 도 matcher 에 넣었는데, 그러면 **모든 셸 명령마다** 훅이 돈다. 여기서 절반은
"안 뜨는 것"을 지키는 테스트다 — 기존 경로 규칙이 셸 명령에 새는 순간 이 기능은 소음이 된다.
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / "core" / "hooks" / "memory-search.py"
TEMPLATE_ROUTES = ROOT / "project-template" / ".claude" / "memory" / "routes.json"


def _bash(command):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": command}}


def _edit(file_path, new_string="x"):
    return {"hook_event_name": "PreToolUse", "tool_name": "Edit",
            "tool_input": {"file_path": file_path, "new_string": new_string}}


class _Hook(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = pathlib.Path(self._tmp.name)
        self.memory = self.project / ".claude" / "memory"
        self.memory.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write_routes(self, rules):
        (self.memory / "routes.json").write_text(
            json.dumps({"rules": rules}), encoding="utf-8")

    def write_memory(self, name, body):
        (self.memory / name).write_text(body, encoding="utf-8")

    def run_hook(self, payload):
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.project)
        proc = subprocess.run(
            ["python3", str(HOOK)], input=json.dumps(payload),
            capture_output=True, text=True, env=env, cwd=self.project,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        if not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]


class CommandRouteTest(_Hook):
    def setUp(self):
        super().setUp()
        self.write_routes([
            {"command_contains": ["gh pr create"], "memory": ["review-rule.md"]},
        ])
        self.write_memory("review-rule.md", "리뷰 결과는 PR 댓글에 남긴다")

    def test_matching_command_injects_the_memory(self):
        out = self.run_hook(_bash('gh pr create --base main --title "x"'))

        self.assertIsNotNone(out, "명령 규칙이 안 걸렸다 — 규칙이 필요한 순간에 못 닿는다")
        self.assertIn("리뷰 결과는 PR 댓글에 남긴다", out)

    def test_match_is_case_insensitive(self):
        self.assertIsNotNone(self.run_hook(_bash("GH PR CREATE --base main")))

    def test_unrelated_command_is_silent(self):
        self.assertIsNone(self.run_hook(_bash("ls -la")))

    def test_command_rule_does_not_fire_on_edits(self):
        """`gh pr create` 라는 글자가 파일 경로에 있을 리 없지만, 계약을 고정한다."""
        self.assertIsNone(self.run_hook(_edit("/repo/gh pr create.md")))


class CommandQuotingAPatchTest(_Hook):
    """패치 원문을 **인용한** 셸 명령. 편집으로 오인하면 바로 그 순간에 규칙이 빠진다.

    `gh pr create --body "...*** Begin Patch..."` 처럼 PR 본문에 패치를 붙이는 일이 실제로
    있다. 내용만 보고 판정하면 이 경우가 조용히 새는데, 하필 이 기능이 겨냥한 그 순간이다.
    """

    def setUp(self):
        super().setUp()
        self.write_routes([
            {"command_contains": ["gh pr create"], "memory": ["review-rule.md"]},
            {"contains": ["test.txt"], "memory": ["path-rule.md"]},
        ])
        self.write_memory("review-rule.md", "리뷰 규칙")
        self.write_memory("path-rule.md", "경로 규칙")

    def test_command_route_still_fires(self):
        payload = _bash('gh pr create --body "*** Begin Patch\n*** Add File: test.txt\n+x\n*** End Patch"')

        out = self.run_hook(payload)

        self.assertIn("리뷰 규칙", out or "")

    def test_quoted_patch_is_not_parsed_as_an_edit(self):
        payload = _bash('gh pr create --body "*** Begin Patch\n*** Add File: test.txt\n+x\n*** End Patch"')

        out = self.run_hook(payload) or ""

        self.assertNotIn("경로 규칙", out, "인용된 패치를 편집으로 파싱해 엉뚱한 경로로 라우팅했다")


class PathRulesStayPathScopedTest(_Hook):
    """경로 키가 셸 명령으로 새면 이 기능은 쓸 수 없게 된다."""

    def setUp(self):
        super().setUp()
        self.write_routes([
            {"contains": ["hook"], "memory": ["hook-rule.md"]},
            {"glob": "*.py", "memory": ["py-rule.md"]},
        ])
        self.write_memory("hook-rule.md", "훅 규칙")
        self.write_memory("py-rule.md", "파이썬 규칙")

    def test_contains_does_not_match_a_command_mentioning_it(self):
        self.assertIsNone(self.run_hook(_bash("grep -rn hook core/")),
                          "읽기 전용 검색 명령에 메모리가 쏟아진다")

    def test_glob_does_not_match_a_command_mentioning_a_file(self):
        self.assertIsNone(self.run_hook(_bash("python3 build.py")))

    def test_path_rules_still_work_on_edits(self):
        out = self.run_hook(_edit("/repo/core/hooks/x.py"))

        self.assertIn("훅 규칙", out)
        self.assertIn("파이썬 규칙", out)


class MatchEmptyStaysEditOnlyTest(_Hook):
    """`match_empty` 가 셸 명령에도 걸리면 **모든 명령마다** 발화한다."""

    def setUp(self):
        super().setUp()
        self.write_routes([
            {"contains": ["git"], "match_empty": True, "memory": ["git-rule.md"]},
        ])
        self.write_memory("git-rule.md", "git 규칙")

    def test_shell_command_does_not_trigger_match_empty(self):
        for command in ("ls", "echo hello", "git status"):
            self.assertIsNone(self.run_hook(_bash(command)), command)

    def test_edit_without_a_path_still_triggers_match_empty(self):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Edit",
                   "tool_input": {"new_string": "내용만 있고 경로 없음"}}

        self.assertIn("git 규칙", self.run_hook(payload) or "")


class ShippedTemplateIsQuietTest(_Hook):
    """template 을 그대로 복사한 프로젝트가 셸 명령마다 소음을 내면 안 된다.

    template 의 `{"contains": ["git"], "match_empty": true}` 가 정확히 그 위험이다.
    """

    def setUp(self):
        super().setUp()
        shutil.copy(TEMPLATE_ROUTES, self.memory / "routes.json")
        (self.memory / "decisions").mkdir()
        (self.memory / "decisions" / "git-workflow.md").write_text("git 워크플로", encoding="utf-8")
        (self.memory / "patterns").mkdir()
        (self.memory / "patterns" / "code-quality.md").write_text("품질", encoding="utf-8")

    def test_ordinary_shell_commands_are_silent(self):
        for command in ("ls -la", "git status", "npm test", "cat README.md"):
            self.assertIsNone(self.run_hook(_bash(command)), command)

    def test_the_templates_command_rule_still_fires(self):
        out = self.run_hook(_bash("gh pr create --base main"))

        self.assertIn("git 워크플로", out or "")


if __name__ == "__main__":
    unittest.main()
