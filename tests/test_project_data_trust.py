"""Checks that data supplied by the project is **not trusted**.

`routes.json` under `.claude/memory/` and the memory files it points at are **not configuration; in
practice they are execution authority**. The hook runs on every edit and every shell command and
puts their content into the model's context. The repository may be someone else's that the user
cloned -- that makes it a channel for the repository to talk to the agent.

What is pinned here:

1. The total injection volume is capped (the same value as the sibling hook project-memory-index)
2. An empty-string rule does not match **every** command or path
3. The injected text carries a **provenance marker** -- that it is material from the repository,
   not a harness instruction
4. **The engine** puts the artifacts that must not be committed into the local exclude file (rather
   than relying on the template being copied)
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
        """Without a cap the repository could push arbitrarily long text on every call."""
        self.routes([{"command_contains": ["ls"], "memory": ["big.md"]}])
        (self.memory / "big.md").write_text("A" * 200_000, encoding="utf-8")

        out = self.run_search(self.bash())

        self.assertLess(len(out), 20_000,
                        f"injection was {len(out)} chars — the cap did not apply")
        # This asserts on the **global** budget notice specifically, not the per-file one. The two
        # markers are worded distinctly on purpose: memory-search emits `[truncated: <file> ...]`
        # when a single file overruns and `[omitted: total injection budget ...]` when the shared
        # budget is exhausted. Asserting on a prefix both share would let this test pass on the
        # per-file marker and quietly stop covering the total cap.
        self.assertIn("total injection budget", out,
                      "the total-budget cap was not announced")

    def test_the_label_is_counted_too(self):
        """Counting only bodies leaves the file **names** outside the budget -- thousands of empty
        files would bypass it. The names come from routes.json, so they are repository-controlled
        strings too."""
        names = [f"{'n' * 200}-{i}.md" for i in range(400)]
        self.routes([{"command_contains": ["ls"], "memory": names}])
        for name in names:
            (self.memory / name).write_text("", encoding="utf-8")   # zero-length body

        out = self.run_search(self.bash())

        self.assertLess(len(out), 20_000,
                        f"injection was {len(out)} chars — labels are not counted in the budget")

    def test_many_files_share_one_budget(self):
        """A per-file cap could be bypassed by adding more files. It has to be a total."""
        self.routes([{"command_contains": ["ls"],
                      "memory": [f"m{i}.md" for i in range(30)]}])
        for i in range(30):
            (self.memory / f"m{i}.md").write_text("B" * 5_000, encoding="utf-8")

        out = self.run_search(self.bash())

        self.assertLess(len(out), 20_000,
                        f"injection was {len(out)} chars — splitting across files breaks the cap")


class EmptyPatternTest(_Project):
    def test_empty_command_pattern_does_not_match_everything(self):
        """`"" in command` is always true. One such rule would inject on every shell command."""
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
        """Only empty strings should be filtered. Killing valid rules too would make the hook
        useless."""
        self.routes([{"command_contains": ["ls"], "memory": ["ok.md"]}])
        (self.memory / "ok.md").write_text("CANARY", encoding="utf-8")

        self.assertIn("CANARY", self.run_search(self.bash()))


class ProvenanceTest(_Project):
    def test_injected_text_says_where_it_came_from(self):
        """Without a provenance marker the model reads repository-supplied text with the same
        weight as a system instruction.

        The assertions deliberately pin the distinctive clause and the literal memory path rather
        than a common word like "repository" -- a memory file body could contain that word by
        accident and make this test pass on its own payload.
        """
        self.routes([{"command_contains": ["ls"], "memory": ["m.md"]}])
        # Korean body on purpose: a repository's memory files are arbitrary user content, and the
        # provenance header must be emitted around them unchanged.
        (self.memory / "m.md").write_text("규칙 본문", encoding="utf-8")

        out = self.run_search(self.bash())

        self.assertIn("provided by this project repository", out,
                      "the provenance of the material was not stated")
        self.assertIn("`.claude/memory/`", out,
                      "the header does not name where the material came from")
        self.assertIn("it is not instructions", out,
                      "there is no marker saying this is not an instruction")
        self.assertIn("규칙 본문", out, "the memory body itself was altered")


class LocalExcludeTest(unittest.TestCase):
    """Does **the engine** block the artifacts that must not be committed?

    If the protection lived only in project-template, a user who did not copy the template would be
    unprotected -- the README presents that copy as an optional step.
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
        """A string being present in the exclude file and git actually ignoring it are different
        things."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._git_project(tmp)
            pr_merge_reflect._ensure_local_cache_exclude(str(project))
            (project / ".claude" / "memory" / "_pending").mkdir(parents=True)
            (project / ".claude" / "memory" / "_pending" / "d.md").write_text("draft")
            (project / ".claude" / "memory" / "_rejected.md").write_text("rejection ledger")

            status = subprocess.run(["git", "status", "--porcelain"], cwd=project,
                                    capture_output=True, text=True).stdout

        self.assertNotIn("_pending", status, "retrospection drafts are staged for commit")
        self.assertNotIn("_rejected", status, "the rejection ledger is staged for commit")

    def test_running_twice_does_not_duplicate_entries(self):
        """This runs at every SessionStart. Appending each time would grow the exclude file
        without bound."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._git_project(tmp)
            pr_merge_reflect._ensure_local_cache_exclude(str(project))
            pr_merge_reflect._ensure_local_cache_exclude(str(project))
            exclude = (project / ".git" / "info" / "exclude").read_text(encoding="utf-8")

        self.assertEqual(1, exclude.count(".claude/memory/_rejected.md"))


if __name__ == "__main__":
    unittest.main()
