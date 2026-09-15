"""Do the edit hooks run on Codex `apply_patch` input too (issue #85, step 2)?

The hooks are **actually executed** and their stdout inspected. Testing at function level alone
misses wiring gaps like "normalisation works but the hook never uses it" -- which happened twice this
week.

Claude input runs through the same assertions. Not breaking the existing behaviour during the port
is the completion condition.
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
PROJECT_INDEX = ROOT / "core" / "hooks" / "project-memory-index.py"

# Measured input from the body of issue #85 (codex-cli 0.145.0).
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

    def run_hook(self, script, payload, *, use_env=True, cwd=None):
        env = dict(os.environ)
        # Even if the parent process is a retrospection job, this test must exercise the hook itself.
        env.pop("REFLECT_JOB", None)
        if use_env:
            env["CLAUDE_PROJECT_DIR"] = str(self.project)
        else:
            env.pop("CLAUDE_PROJECT_DIR", None)
        proc = subprocess.run(
            ["python3", str(script)], input=json.dumps(payload),
            capture_output=True, text=True, env=env, cwd=cwd or self.project,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        return proc.stdout.strip()

    def context_of(self, stdout):
        """The text the hook injected. None when it emitted nothing."""
        if not stdout:
            return None
        payload = json.loads(stdout)
        nested = (payload.get("hookSpecificOutput") or {}).get("additionalContext")
        top = payload.get("additionalContext")
        # If the two keys differ, the outcome depends on which one a given tool reads -- they have
        # to match.
        self.assertEqual(nested, top,
                         "the nested and top-level additionalContext values diverged")
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
        # Korean memory bodies on purpose: these are project-supplied content that the hook must
        # carry through byte-for-byte.
        (self.memory / "txt-rule.md").write_text("텍스트 파일 규칙", encoding="utf-8")
        (self.memory / "service-rule.md").write_text("서비스 규칙", encoding="utf-8")

    def test_codex_patch_triggers_the_matching_rule(self):
        out = self.context_of(self.run_hook(MEMORY_SEARCH, _codex(CODEX_PATCH)))

        self.assertIsNotNone(out, "nothing was injected for Codex patch input")
        self.assertIn("텍스트 파일 규칙", out)

    def test_codex_payload_cwd_wins_when_process_runs_elsewhere(self):
        payload = _codex(CODEX_PATCH)
        payload["cwd"] = str(self.project)

        with tempfile.TemporaryDirectory() as elsewhere:
            out = self.context_of(self.run_hook(
                MEMORY_SEARCH, payload, use_env=False, cwd=elsewhere
            ))

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
        self.assertIn("서비스 규칙", out,
                      "the patch's second file was left out of the routing")

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
                {"glob": "*.py", "regex": "print\\(",
                 "message": "print used {count} time(s) — consider a logger"},
            ]
        }), encoding="utf-8")

    def test_codex_patch_content_is_inspected(self):
        patch = ("*** Begin Patch\n*** Add File: a.py\n"
                 "+print('x')\n+# TODO: 나중에\n*** End Patch")

        out = self.context_of(self.run_hook(REFLECTION, _codex(patch, "PostToolUse")))

        self.assertIn("TODO/FIXME", out)
        self.assertIn("remove it once the work is done", out,
                      "the built-in TODO warning text is missing")
        self.assertIn("print used 1 time(s)", out)

    def test_codex_payload_cwd_loads_rules_when_process_runs_elsewhere(self):
        patch = "*** Begin Patch\n*** Add File: a.py\n+print('x')\n*** End Patch"
        payload = _codex(patch, "PostToolUse")
        payload["cwd"] = str(self.project)

        with tempfile.TemporaryDirectory() as elsewhere:
            out = self.context_of(self.run_hook(
                REFLECTION, payload, use_env=False, cwd=elsewhere
            ))

        self.assertIn("print used 1 time(s)", out)

    def test_claude_edit_still_works(self):
        out = self.context_of(self.run_hook(
            REFLECTION, _claude("a.py", "print('x')", "PostToolUse")))

        self.assertIn("print used 1 time(s)", out)

    def test_glob_rule_does_not_see_another_files_content(self):
        """Merging content instead of applying rules per file would let a *.py rule see .md
        content."""
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


class ProjectMemoryIndexTest(_HookRun):
    def test_codex_payload_cwd_loads_index_when_process_runs_elsewhere(self):
        (self.memory / "INDEX.md").write_text("payload cwd canary", encoding="utf-8")
        payload = {"hook_event_name": "SessionStart", "cwd": str(self.project)}

        with tempfile.TemporaryDirectory() as elsewhere:
            stdout = self.run_hook(PROJECT_INDEX, payload, use_env=False, cwd=elsewhere)
        out = (json.loads(stdout).get("hookSpecificOutput") or {}).get("additionalContext")

        self.assertIn("payload cwd canary", out)


if __name__ == "__main__":
    unittest.main()
