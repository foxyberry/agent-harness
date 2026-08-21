"""편집 훅 입력 정규화 — Claude 와 Codex 를 같은 모델로 (이슈 #85 1단계).

Codex 픽스처는 **실측 원문**이다(codex-cli 0.145.0). 앞선 판들이 rollout 로그를 역추론해
도구 이름을 `exec` 로 잘못 알았던 전례가 있어서, 여기서는 실제로 관측된 입력을 그대로 쓴다.
"""
import importlib.util
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "core" / "scripts" / "hook_io.py"
SPEC = importlib.util.spec_from_file_location("hook_io", SCRIPT)
hook_io = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook_io)

EditedFile = hook_io.EditedFile

# 이슈 #85 본문의 실측 입력 그대로.
CODEX_ADD = {
    "hook_event_name": "PreToolUse",
    "tool_name": "apply_patch",
    "tool_input": {
        "command": "*** Begin Patch\n*** Add File: /tmp/x/test.txt\n+world\n*** End Patch",
    },
    "tool_use_id": "exec-9fa03e9a-13d8-438e-bb96-796a2717a0fe",
}


class CodexPatchTest(unittest.TestCase):
    def test_measured_fixture_from_the_issue(self):
        self.assertEqual(
            [EditedFile("/tmp/x/test.txt", "world")],
            hook_io.edited_files(CODEX_ADD),
        )

    def test_one_patch_can_touch_several_files(self):
        data = {"tool_input": {"command": "\n".join([
            "*** Begin Patch",
            "*** Add File: a.py",
            "+import os",
            "*** Update File: b.py",
            "@@ def main():",
            "-    old()",
            "+    new()",
            " context",
            "*** End Patch",
        ])}}

        self.assertEqual(
            [EditedFile("a.py", "import os"), EditedFile("b.py", "    new()")],
            hook_io.edited_files(data),
        )

    def test_removed_and_context_lines_are_not_added_content(self):
        data = {"tool_input": {"command": "\n".join([
            "*** Begin Patch",
            "*** Update File: x.py",
            "@@",
            "-지운 줄",
            " 그대로인 줄",
            "+넣은 줄",
            "*** End Patch",
        ])}}

        self.assertEqual("넣은 줄", hook_io.edited_files(data)[0].added)

    def test_move_to_destination_becomes_the_path(self):
        """내용이 최종적으로 사는 곳은 목적지다."""
        data = {"tool_input": {"command": "\n".join([
            "*** Begin Patch",
            "*** Update File: old/name.py",
            "*** Move to: new/name.py",
            "+moved",
            "*** End Patch",
        ])}}

        self.assertEqual([EditedFile("new/name.py", "moved")],
                         hook_io.edited_files(data))

    def test_delete_is_listed_with_no_content(self):
        """memory-search 는 삭제도 '건드린 파일'로 봐야 한다. reflection 은 내용이 없어 건너뛴다."""
        data = {"tool_input": {"command":
                               "*** Begin Patch\n*** Delete File: gone.py\n*** End Patch"}}

        self.assertEqual([EditedFile("gone.py", "")], hook_io.edited_files(data))

    def test_code_starting_with_two_plus_signs_survives(self):
        """`++counter;` 는 패치에서 `+++counter;` 가 된다.

        이걸 unified diff 헤더로 오인해 버리면 그 코드가 품질 검사에서 조용히 빠진다.
        apply_patch 는 파일을 `*** ... File:` 마커로 표시하고 `+++ b/path` 헤더를 쓰지 않으므로,
        `+++` 를 헤더로 볼 이유가 애초에 없다.
        """
        data = {"tool_input": {"command": "\n".join([
            "*** Begin Patch",
            "*** Update File: x.c",
            "@@",
            " int counter = 0;",   # context (앞이 공백)
            "+++counter;",         # 추가된 `++counter;`
            "*** End Patch",
        ])}}

        self.assertEqual("++counter;", hook_io.edited_files(data)[0].added)


class ClaudeShapeTest(unittest.TestCase):
    def test_edit(self):
        data = {"tool_input": {"file_path": "/repo/a.kt", "new_string": "val x = 1"}}
        self.assertEqual([EditedFile("/repo/a.kt", "val x = 1")],
                         hook_io.edited_files(data))

    def test_write(self):
        data = {"tool_input": {"file_path": "/repo/new.md", "content": "# 제목"}}
        self.assertEqual([EditedFile("/repo/new.md", "# 제목")],
                         hook_io.edited_files(data))

    def test_multiedit_joins_every_new_string(self):
        data = {"tool_input": {"file_path": "/repo/a.kt", "edits": [
            {"new_string": "첫째"}, {"new_string": "둘째"},
        ]}}
        self.assertEqual([EditedFile("/repo/a.kt", "첫째\n둘째")],
                         hook_io.edited_files(data))

    def test_path_without_content_still_counts_as_an_edited_file(self):
        data = {"tool_input": {"file_path": "/repo/a.kt"}}
        self.assertEqual([EditedFile("/repo/a.kt", "")], hook_io.edited_files(data))


class FailOpenTest(unittest.TestCase):
    def test_shell_command_is_not_an_edit(self):
        self.assertEqual([], hook_io.edited_files(
            {"tool_name": "Bash", "tool_input": {"command": "echo hello"}}))

    def test_garbage_returns_empty(self):
        for junk in (None, {}, {"tool_input": None}, {"tool_input": "문자열"},
                     {"tool_input": {"file_path": 42}}):
            self.assertEqual([], hook_io.edited_files(junk), junk)


class ConvenienceTest(unittest.TestCase):
    def test_paths_and_content_helpers(self):
        data = {"tool_input": {"command": "\n".join([
            "*** Begin Patch",
            "*** Add File: a.py",
            "+하나",
            "*** Add File: b.py",
            "+둘",
            "*** End Patch",
        ])}}

        self.assertEqual(["a.py", "b.py"], hook_io.edited_paths(data))
        self.assertEqual("하나\n둘", hook_io.added_content(data))


class ProjectDirTest(unittest.TestCase):
    def test_environment_wins_over_payload_and_process_cwd(self):
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": "/from-env"}):
            self.assertEqual("/from-env", hook_io.project_dir({"cwd": "/from-payload"}))

    def test_payload_cwd_is_used_when_environment_is_absent(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual("/from-payload", hook_io.project_dir({"cwd": "/from-payload"}))

    def test_process_cwd_is_the_final_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {}, clear=True), patch.object(os, "getcwd", return_value=tmp):
            self.assertEqual(tmp, hook_io.project_dir({}))


if __name__ == "__main__":
    unittest.main()
