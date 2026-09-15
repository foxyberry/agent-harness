"""Edit-hook input normalization — one model for Claude and Codex (issue #85, step 1).

The Codex fixtures are **raw measured input** (codex-cli 0.145.0). Earlier revisions
inferred the tool name from rollout logs and got it wrong (`exec`), so here we use the
input exactly as it was observed.

Korean fixture content is deliberate: it is the only non-ASCII payload flowing through the
normalizer, and it pins down that multibyte content survives unchanged. Do not translate
it — the explanatory prose is English, the payloads are data.
"""
import contextlib
import importlib.util
import io
import json
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

# The measured input from the body of issue #85, verbatim.
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
        # Korean payload on purpose: "removed line" / "unchanged line" / "added line".
        # Only the added one may come back, and it must come back byte-identical.
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
        """The content ends up living at the destination path."""
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
        """memory-search must treat a deletion as a 'touched file' too; reflection skips it for lack of content."""
        data = {"tool_input": {"command":
                               "*** Begin Patch\n*** Delete File: gone.py\n*** End Patch"}}

        self.assertEqual([EditedFile("gone.py", "")], hook_io.edited_files(data))

    def test_code_starting_with_two_plus_signs_survives(self):
        """`++counter;` becomes `+++counter;` inside a patch.

        Mistaking that for a unified diff header silently drops the code from the quality
        checks. apply_patch marks files with `*** ... File:` markers and never writes a
        `+++ b/path` header, so there is no reason to read `+++` as a header at all.
        """
        data = {"tool_input": {"command": "\n".join([
            "*** Begin Patch",
            "*** Update File: x.c",
            "@@",
            " int counter = 0;",   # context line (leading space)
            "+++counter;",         # the added `++counter;`
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
        # Korean payload on purpose: "first" / "second", joined in order.
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
        # `"문자열"` is a bare string where a dict is expected — a wrong-type payload.
        for junk in (None, {}, {"tool_input": None}, {"tool_input": "문자열"},
                     {"tool_input": {"file_path": 42}}):
            self.assertEqual([], hook_io.edited_files(junk), junk)


class ConvenienceTest(unittest.TestCase):
    def test_paths_and_content_helpers(self):
        # Korean payload on purpose: "one" / "two", one added line per file.
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


class EmitContextTest(unittest.TestCase):
    """The injection payload: both keys, and non-ASCII text passed through intact.

    Now that the hooks generate English text, nothing in the default path exercises
    non-ASCII output any more. But injected context still carries whatever the project's
    memory files and the user's own content say, which is frequently not ASCII. This pins
    `ensure_ascii=False` so that content is not silently mangled into `\\uXXXX` escapes.
    """

    def _emit(self, text):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            hook_io.emit_context("PreToolUse", text)
        return buffer.getvalue()

    def test_both_the_nested_and_top_level_keys_are_emitted(self):
        """Claude reads the nested key; the Codex docs are ambiguous — emit both."""
        payload = json.loads(self._emit("hello"))
        self.assertEqual("hello", payload["additionalContext"])
        self.assertEqual("hello", payload["hookSpecificOutput"]["additionalContext"])
        self.assertEqual("PreToolUse", payload["hookSpecificOutput"]["hookEventName"])

    def test_non_ascii_context_survives_unescaped(self):
        korean = "메모리 규칙: 커밋 전에 ./build.sh 를 돌릴 것"
        raw = self._emit(korean)
        self.assertIn(korean, raw, "non-ASCII context was escaped instead of written as is")
        self.assertEqual(korean, json.loads(raw)["additionalContext"])

    def test_empty_text_emits_nothing(self):
        """An empty injection must stay silent — otherwise a hollow JSON line gets emitted."""
        self.assertEqual("", self._emit(""))
        self.assertEqual("", self._emit(None))


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
