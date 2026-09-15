"""Pins that the retrospection skip rules filter out **retrospection-output PRs** (issue #130).

#36 introduced the skip rules but left two holes.

1. The skip paths covered only the `.claude/memory/**` family, so a PR that **promoted a lesson into
   a rule** (`CLAUDE.md`, `AGENTS.md`, `.claude/agents/**`) was not caught.
2. The verdict used `all()`, so **a single file defeated it**. One `.gitignore` line releases the
   skip.

The result was a loop -- a PR produced by a retrospective demands its own retrospective.

## Engine and data are examined separately

The first attempt at a fix put the broad list into the **engine defaults**. A Codex review and our
own check found the same problem from both sides: that makes retrospectives for genuine rule changes
and `.gitignore` policy changes disappear **silently**. That is harder to notice than the loop.

The principle in `AGENTS.md` was already the answer -- the engine is generic, "what" is project data.
`.claude/memory/**` is a path the harness creates itself, so the engine may know about it, but
`CLAUDE.md` and `.gitignore` are **that project's files**, and how much they are worth reflecting on
differs per project.

So the two layers are pinned **separately**:

- `EngineDefaultsTest` -- the engine defaults know only about harness output. They know nothing
  about project files.
- `TemplateDataTest` -- in a project with the template data installed, the reported case really is
  blocked.

Looking at them mixed together would hide which of the two is doing the work, and a later quiet
broadening of the defaults would still pass.
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
    """Calls the real `_should_skip_reflect`. Only the PR lookup (`gh`) is faked.

    WARNING: never copy the verdict logic in here. The first version did, and **the test failed to
    catch** a mutation that deleted the production filter -- because it was exercising a copy. Only
    the network is faked; the rules always come from the real thing.
    """
    details = {"labels": [], "commit_messages": [], "files": list(files)}
    with patch.object(prm, "_pr_details", return_value=details):
        return prm._should_skip_reflect(project_dir, 1)


class _Project(unittest.TestCase):
    """An empty project with no config file. Set `skip_config` to install one."""

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
    """With no config data. The engine knows about **harness output only**."""

    def test_harness_output_is_skipped(self):
        for files in ([".claude/memory/lesson.md", ".claude/memory/INDEX.md"],
                      [".claude/handoff/main.md"],
                      [".agents/skills/fw/SKILL.md"]):
            with self.subTest(files=files):
                self.assertTrue(self.skip(files))

    def test_engine_does_not_decide_about_project_files(self):
        """`CLAUDE.md` and `AGENTS.md` are project files -- the engine does not decide whether they
        are worth reflecting on.

        This repository is the example. #105 narrowed the harness's scope via `AGENTS.md`; that was
        a major decision and worth a retrospective. For another team the same file is boilerplate.
        """
        for files in (["AGENTS.md"], ["CLAUDE.md"], [".claude/agents/reviewer.md"],
                      [".claude/skills/foo/SKILL.md"]):
            with self.subTest(files=files):
                self.assertFalse(self.skip(files),
                                 "the engine defaults are swallowing project files too")

    def test_engine_ships_no_ignore_list(self):
        """The mechanism ships and the list is empty -- the project decides what is incidental."""
        self.assertIn("ignore_paths", prm.DEFAULT_REFLECT_SKIP)
        self.assertEqual([], prm.DEFAULT_REFLECT_SKIP["ignore_paths"])
        self.assertFalse(self.skip([".claude/memory/x.md", ".gitignore"]),
                         "without data the engine must not declare .gitignore incidental")

    def test_real_work_is_reflected(self):
        self.assertFalse(self.skip(["README.md", "docs/guide.md", "tests/t.py"]))

    def test_code_mixed_with_memory_is_reflected(self):
        self.assertFalse(self.skip(["core/hooks/reflect.py", ".claude/memory/x.md"]))

    def test_empty_file_list_is_not_a_skip(self):
        self.assertFalse(self.skip([]))


class TemplateDataTest(_Project):
    """A project with the template data installed. The reported loop is blocked here."""

    skip_config = TEMPLATE

    def test_the_reported_loop_case_is_skipped(self):
        """Exactly the PR reported in issue #130. This file's regression case."""
        files = [".claude/memory/lesson.md", ".claude/memory/INDEX.md",
                 "CLAUDE.md", ".claude/agents/qa-engineer.md", ".gitignore"]
        self.assertTrue(self.skip(files),
                        "a retrospection-output PR is demanding a retrospective again — "
                        "the loop has returned")

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
        """Even with the broadened data installed, real work stays in scope for retrospection.

        This is the more important direction -- if skipping goes too far, retrospectives disappear
        with neither a warning nor a failure.
        """
        self.assertFalse(self.skip(["README.md", "docs/guide.md", "tests/t.py"]))

    def test_code_mixed_with_rules_is_still_reflected(self):
        self.assertFalse(self.skip(["core/hooks/reflect.py", "AGENTS.md"]))

    def test_only_incidental_files_is_not_a_skip(self):
        """With only incidental files left there are no grounds for a verdict -- fail-open
        (reflect)."""
        self.assertFalse(self.skip([".gitignore"]))


class ReflectSkipConfigTest(unittest.TestCase):
    """Does the config loader handle new keys? If it is not extended alongside them, it silently
    lags behind."""

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
        """If `defaults: false` misses even one key, reading that key raises KeyError."""
        cfg = self._cfg({"defaults": False, "paths": ["only/**"]})
        self.assertEqual(["only/**"], cfg["paths"])
        for key in prm.DEFAULT_REFLECT_SKIP:
            with self.subTest(key=key):
                self.assertIn(key, cfg)

    def test_every_default_key_is_extendable(self):
        """Adding a key to the defaults without adding it to the extend loop leaves users unable to
        extend it."""
        probe = {k: ["zz-probe"] for k in prm.DEFAULT_REFLECT_SKIP}
        cfg = self._cfg(probe)
        for key in prm.DEFAULT_REFLECT_SKIP:
            with self.subTest(key=key):
                self.assertIn("zz-probe", cfg[key])

    def test_shipped_template_parses_and_covers_both_layers(self):
        """Does the template actually load? Broken syntax is silently ignored (except: return
        cfg)."""
        cfg = prm._load_reflect_skip_config(str(TEMPLATE.parents[2]))
        self.assertIn("AGENTS.md", cfg["paths"])
        self.assertIn(".gitignore", cfg["ignore_paths"])


if __name__ == "__main__":
    unittest.main()
