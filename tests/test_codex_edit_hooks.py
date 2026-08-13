"""편집 훅이 Codex `apply_patch` 입력에도 도는지 (이슈 #85 2단계).

훅을 **실제로 실행**해서 stdout 을 본다. 함수 단위로만 보면 "정규화는 되는데 훅이 안 쓴다"
같은 배선 누락을 놓친다 — 이번 주에 두 번 그랬다.

Claude 입력도 같은 단언으로 함께 돌린다. 이식이 기존 동작을 깨지 않았는지가 완료 조건이다.
"""
import json
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MEMORY_SEARCH = ROOT / "core" / "hooks" / "memory-search.py"
REFLECTION = ROOT / "core" / "hooks" / "reflection.py"

# 이슈 #85 본문의 실측 입력 (codex-cli 0.145.0).
CODEX_PATCH = ("*** Begin Patch\n"
               "*** Add File: /tmp/x/test.txt\n"
               "+world\n"
               "*** End Patch")


def _codex(tool_input_command, event="PreToolUse"):
    return {"hook_event_name": event, "tool_name": "apply_patch",
            "tool_input": {"command": tool_input_command},
            "tool_use_id": "exec-9fa03e9a-13d8-438e-bb96-796a2717a0fe"}


def _claude(file_path, new_string, event="PreToolUse"):
    return {"hook_event_name": event, "tool_name": "Edit",
            "tool_input": {"file_path": file_path, "new_string": new_string}}


class _HookRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = pathlib.Path(self._tmp.name)
        self.memory = self.project / ".claude" / "memory"
        self.memory.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def run_hook(self, script, payload):
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.project)
        proc = subprocess.run(
            ["python3", str(script)], input=json.dumps(payload),
            capture_output=True, text=True, env=env, cwd=self.project,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        return proc.stdout.strip()

    def context_of(self, stdout):
        """훅이 주입한 텍스트. 아무것도 안 냈으면 None."""
        if not stdout:
            return None
        payload = json.loads(stdout)
        nested = (payload.get("hookSpecificOutput") or {}).get("additionalContext")
        top = payload.get("additionalContext")
        # 두 키가 서로 다르면 어느 쪽을 읽는 툴이냐에 따라 결과가 갈린다 — 같아야 한다.
        self.assertEqual(nested, top, "중첩/최상위 additionalContext 가 어긋났다")
        return nested


class MemorySearchTest(_HookRun):
    def setUp(self):
        super().setUp()
        (self.memory / "routes.json").write_text(json.dumps({
            "rules": [
                {"glob": "*.txt", "memory": ["txt-rule.md"]},
                {"contains": ["service"], "memory": ["service-rule.md"]},
            ]
        }), encoding="utf-8")
        (self.memory / "txt-rule.md").write_text("텍스트 파일 규칙", encoding="utf-8")
        (self.memory / "service-rule.md").write_text("서비스 규칙", encoding="utf-8")

    def test_codex_patch_triggers_the_matching_rule(self):
        out = self.context_of(self.run_hook(MEMORY_SEARCH, _codex(CODEX_PATCH)))

        self.assertIsNotNone(out, "Codex 패치 입력에서 아무것도 주입하지 않았다")
        self.assertIn("텍스트 파일 규칙", out)

    def test_claude_edit_still_works(self):
        out = self.context_of(self.run_hook(MEMORY_SEARCH, _claude("/repo/a.txt", "x")))

        self.assertIn("텍스트 파일 규칙", out)

    def test_every_file_in_one_patch_is_routed(self):
        patch = "\n".join([
            "*** Begin Patch",
            "*** Add File: notes.txt",
            "+hello",
            "*** Add File: app/service/user.py",
            "+def get(): ...",
            "*** End Patch",
        ])

        out = self.context_of(self.run_hook(MEMORY_SEARCH, _codex(patch)))

        self.assertIn("텍스트 파일 규칙", out)
        self.assertIn("서비스 규칙", out, "패치의 두 번째 파일이 라우팅에서 빠졌다")

    def test_deleted_file_is_still_routed(self):
        patch = "*** Begin Patch\n*** Delete File: notes.txt\n*** End Patch"

        out = self.context_of(self.run_hook(MEMORY_SEARCH, _codex(patch)))

        self.assertIn("텍스트 파일 규칙", out)

    def test_no_routes_file_is_silent(self):
        (self.memory / "routes.json").unlink()

        self.assertEqual("", self.run_hook(MEMORY_SEARCH, _codex(CODEX_PATCH)))


class ReflectionTest(_HookRun):
    def setUp(self):
        super().setUp()
        (self.memory / "reflection-rules.json").write_text(json.dumps({
            "rules": [
                {"glob": "*.py", "regex": "print\\(", "message": "print {count}개 — 로거 사용 검토"},
            ]
        }), encoding="utf-8")

    def test_codex_patch_content_is_inspected(self):
        patch = ("*** Begin Patch\n*** Add File: a.py\n"
                 "+print('x')\n+# TODO: 나중에\n*** End Patch")

        out = self.context_of(self.run_hook(REFLECTION, _codex(patch, "PostToolUse")))

        self.assertIn("TODO/FIXME", out)
        self.assertIn("print 1개", out)

    def test_claude_edit_still_works(self):
        out = self.context_of(self.run_hook(
            REFLECTION, _claude("a.py", "print('x')", "PostToolUse")))

        self.assertIn("print 1개", out)

    def test_glob_rule_does_not_see_another_files_content(self):
        """규칙을 파일마다 적용하지 않고 내용을 합치면 *.py 규칙이 .md 내용을 본다."""
        patch = "\n".join([
            "*** Begin Patch",
            "*** Add File: notes.md",
            "+print('문서 안의 예시 코드')",
            "*** End Patch",
        ])

        self.assertEqual("", self.run_hook(REFLECTION, _codex(patch, "PostToolUse")))

    def test_removed_lines_are_not_treated_as_new_code(self):
        patch = "\n".join([
            "*** Begin Patch",
            "*** Update File: a.py",
            "@@",
            "-print('지운 줄')",
            " context",
            "*** End Patch",
        ])

        self.assertEqual("", self.run_hook(REFLECTION, _codex(patch, "PostToolUse")))

    def test_deleted_file_produces_no_warning(self):
        patch = "*** Begin Patch\n*** Delete File: a.py\n*** End Patch"

        self.assertEqual("", self.run_hook(REFLECTION, _codex(patch, "PostToolUse")))

    def test_shell_command_is_not_inspected(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "echo TODO"},
                   "hook_event_name": "PostToolUse"}

        self.assertEqual("", self.run_hook(REFLECTION, payload))


if __name__ == "__main__":
    unittest.main()
