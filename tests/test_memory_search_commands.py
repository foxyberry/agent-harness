"""Does memory-search fire on shell commands, and is it **quiet when it should be** (issue #90)?

Background: a rule written in a document is not followed if it never reaches the moment it is
needed. "Leave the review results as a comment before opening a PR" has nothing to do with editing a
file, so a memory-search that only fires on edits could never deliver it.

So `Bash` was added to the matcher -- but that makes the hook run on **every shell command**. Half
the tests here pin what must *not* fire: the moment existing path rules leak into shell commands,
this feature becomes noise.

Note on language: memory bodies below stay Korean. They are project-supplied content, and the hook
must carry them through unchanged regardless of the language the harness itself speaks.
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

        self.assertIsNotNone(
            out, "the command rule did not fire — the rule never reaches the moment it is needed")
        self.assertIn("리뷰 결과는 PR 댓글에 남긴다", out,
                      "the memory body was not carried through verbatim")

    def test_match_is_case_insensitive(self):
        self.assertIsNotNone(self.run_hook(_bash("GH PR CREATE --base main")))

    def test_unrelated_command_is_silent(self):
        self.assertIsNone(self.run_hook(_bash("ls -la")))

    def test_command_rule_does_not_fire_on_edits(self):
        """The literal text `gh pr create` will never be in a file path, but pin the contract."""
        self.assertIsNone(self.run_hook(_edit("/repo/gh pr create.md")))


class CommandQuotingAPatchTest(_Hook):
    """A shell command that **quotes** a raw patch. Mistaking it for an edit drops the rule at
    exactly the wrong moment.

    Pasting a patch into a PR body, as in `gh pr create --body "...*** Begin Patch..."`, really
    happens. Judging by content alone lets this case leak silently -- and it is precisely the moment
    this feature was built for.
    """

    def setUp(self):
        super().setUp()
        self.write_routes([
            {"command_contains": ["gh pr create"], "memory": ["review-rule.md"]},
            {"contains": ["test.txt"], "memory": ["path-rule.md"]},
        ])
        self.write_memory("review-rule.md", "리뷰 규칙")     # "review rule"
        self.write_memory("path-rule.md", "경로 규칙")       # "path rule"

    def test_command_route_still_fires(self):
        payload = _bash('gh pr create --body "*** Begin Patch\n*** Add File: test.txt\n+x\n*** End Patch"')

        out = self.run_hook(payload)

        self.assertIn("리뷰 규칙", out or "", "the command route stopped firing")

    def test_quoted_patch_is_not_parsed_as_an_edit(self):
        payload = _bash('gh pr create --body "*** Begin Patch\n*** Add File: test.txt\n+x\n*** End Patch"')

        out = self.run_hook(payload) or ""

        self.assertNotIn("경로 규칙", out,
                         "a quoted patch was parsed as an edit and routed by the wrong path")


class PathRulesStayPathScopedTest(_Hook):
    """If path keys leak into shell commands, this feature becomes unusable."""

    def setUp(self):
        super().setUp()
        self.write_routes([
            {"contains": ["hook"], "memory": ["hook-rule.md"]},
            {"glob": "*.py", "memory": ["py-rule.md"]},
        ])
        self.write_memory("hook-rule.md", "훅 규칙")        # "hook rule"
        self.write_memory("py-rule.md", "파이썬 규칙")       # "python rule"

    def test_contains_does_not_match_a_command_mentioning_it(self):
        self.assertIsNone(self.run_hook(_bash("grep -rn hook core/")),
                          "memory floods a read-only search command")

    def test_glob_does_not_match_a_command_mentioning_a_file(self):
        self.assertIsNone(self.run_hook(_bash("python3 build.py")))

    def test_path_rules_still_work_on_edits(self):
        out = self.run_hook(_edit("/repo/core/hooks/x.py"))

        self.assertIn("훅 규칙", out)
        self.assertIn("파이썬 규칙", out)



class MatchEmptyStaysEditOnlyTest(_Hook):
    """If `match_empty` also fires on shell commands, it fires on **every single command**."""

    def setUp(self):
        super().setUp()
        self.write_routes([
            {"contains": ["git"], "match_empty": True, "memory": ["git-rule.md"]},
        ])
        self.write_memory("git-rule.md", "git 규칙")        # "git rule"

    def test_shell_command_does_not_trigger_match_empty(self):
        for command in ("ls", "echo hello", "git status"):
            self.assertIsNone(self.run_hook(_bash(command)), command)

    def test_edit_without_a_path_still_triggers_match_empty(self):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Edit",
                   "tool_input": {"new_string": "content but no path"}}

        self.assertIn("git 규칙", self.run_hook(payload) or "")


class ShippedTemplateIsQuietTest(_Hook):
    """A project that copied the template verbatim must not make noise on every shell command.

    The template's `{"contains": ["git"], "match_empty": true}` is exactly that risk.
    """

    def setUp(self):
        super().setUp()
        shutil.copy(TEMPLATE_ROUTES, self.memory / "routes.json")
        (self.memory / "decisions").mkdir()
        # The shipped template routes to Korean-named memory files; keep the bodies Korean so this
        # exercises the template as real projects have it.
        (self.memory / "decisions" / "git-workflow.md").write_text("git 워크플로", encoding="utf-8")
        (self.memory / "patterns").mkdir()
        (self.memory / "patterns" / "code-quality.md").write_text("품질", encoding="utf-8")

    def test_ordinary_shell_commands_are_silent(self):
        for command in ("ls -la", "git status", "npm test", "cat README.md"):
            self.assertIsNone(self.run_hook(_bash(command)), command)

    def test_the_templates_command_rule_still_fires(self):
        out = self.run_hook(_bash("gh pr create --base main"))

        self.assertIn("git 워크플로", out or "", "the template's command rule stopped firing")


if __name__ == "__main__":
    unittest.main()
