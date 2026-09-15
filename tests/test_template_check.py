"""template-check: a read-only comparison against the bundled `.claude/memory/` reference (#132).

The opinion pack is copied into a project once, so a project that adopted it early never
receives files added later. `reflect-skip.json` is the case that matters: #130 keeps the broad
skip list out of the engine defaults on purpose, so the retrospective-loop fix only works in a
project that has the template file. These tests pin four things:

1. The reported project state (#132, copied before ADRs and reflect-skip existed) comes back
   with the right statuses — `reflect-skip.json` among the missing.
2. The check stays read-only and never prints project content.
3. Link and special-file handling never reads outside the project, never hangs, and never turns
   "could not look" into "missing" or "all good".
4. Both adapters ship the same reference, and each runs from outside the repository against an
   explicitly named project — including a linked worktree whose primary checkout differs.
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "core" / "scripts" / "template_check.py"
TEMPLATE_MEMORY = ROOT / "project-template" / ".claude" / "memory"
CLAUDE_BIN = ROOT / "plugins" / "harness" / "bin"
CODEX_SKILL = ROOT / "plugins" / "codex" / "skills" / "template-check"
ADAPTER_REFERENCES = [
    CLAUDE_BIN / "template-reference",
    CODEX_SKILL / "scripts" / "template-reference",
]


def run(project, *args, script=SCRIPT, reference=TEMPLATE_MEMORY, cwd=None):
    cmd = [sys.executable, str(script)]
    if project is not None:
        cmd += ["--project-dir", str(project)]
    if reference is not None:
        cmd += ["--reference", str(reference)]
    # A FIFO read would block forever — the timeout turns a hang into a failure.
    return subprocess.run(cmd + list(args), capture_output=True, text=True, timeout=30,
                          cwd=cwd)


def statuses(project, **kw):
    result = run(project, "--json", **kw)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    return data, {f["path"]: f for f in data["files"]}


def tree_files(base):
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())


def mem(rel):
    return ".claude/memory/" + rel


class _Project(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name).resolve()
        self.project = self.base / "project"
        self.memory = self.project / ".claude" / "memory"
        self.memory.mkdir(parents=True)

    def adopt(self, *rels):
        for rel in rels:
            dst = self.memory / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TEMPLATE_MEMORY / rel, dst)


class ReportedProjectStateTest(_Project):
    def test_project_copied_before_adr_and_reflect_skip(self):
        """The #132 report: routes and rules copied, INDEX edited, legacy decisions, no ADR files."""
        self.adopt("routes.json", "reflection-rules.json", "patterns/code-quality.md")
        (self.memory / "INDEX.md").write_text("# Index\n- [git](decisions/git-workflow.md)\n")
        (self.memory / "decisions").mkdir()
        (self.memory / "decisions" / "git-workflow.md").write_text(
            "---\nname: git-workflow\ndescription: legacy\ntype: project\n---\nbody\n")

        data, files = statuses(self.project)

        for rel in ("reflect-skip.json", "decisions/README.md", "README.md", ".gitignore",
                    "decisions/adr-EXAMPLE-positive-only-exclusion.md"):
            self.assertEqual("missing", files[mem(rel)]["status"], rel)
        for rel in ("INDEX.md", "decisions/git-workflow.md"):
            self.assertEqual("differs", files[mem(rel)]["status"], rel)
        for rel in ("routes.json", "reflection-rules.json", "patterns/code-quality.md"):
            self.assertEqual("identical", files[mem(rel)]["status"], rel)
        self.assertTrue(data["complete"])
        # Every reference file is accounted for, in a stable order.
        paths = [f["path"] for f in data["files"]]
        self.assertEqual(sorted(mem(r) for r in tree_files(TEMPLATE_MEMORY)), paths)

    def test_fully_adopted_project_is_identical(self):
        self.adopt(*tree_files(TEMPLATE_MEMORY))
        data, _ = statuses(self.project)
        self.assertEqual(len(data["files"]), data["counts"]["identical"])
        self.assertTrue(data["complete"])

    def test_line_endings_alone_are_not_a_difference(self):
        text = (TEMPLATE_MEMORY / "routes.json").read_bytes()
        (self.memory / "routes.json").write_bytes(text.replace(b"\n", b"\r\n"))
        _, files = statuses(self.project)
        self.assertEqual("identical", files[mem("routes.json")]["status"])

    def test_project_content_is_never_printed(self):
        secret = "PROJECT-SECRET-7f3a"
        (self.memory / "routes.json").write_text(json.dumps({"rules": [], "note": secret}))
        for args in ((), ("--json",), ("--verbose",)):
            result = run(self.project, *args)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn(secret, result.stdout + result.stderr, args)


class TextReportTest(_Project):
    def test_listed_paths_lead_to_real_reference_copies(self):
        """The skill reads reference copies from the text report, so the report must locate them."""
        self.adopt("routes.json")
        (self.memory / "INDEX.md").write_text("custom\n")
        lines = run(self.project).stdout.splitlines()
        ref = next(l.split(":", 1)[1].strip() for l in lines if l.startswith("Reference:"))
        listed = [l.strip() for l in lines if l.startswith("  .claude/memory/")]
        self.assertIn(".claude/memory/INDEX.md", listed)
        self.assertIn(".claude/memory/reflect-skip.json", listed)
        for path in listed:
            self.assertTrue(os.path.isfile(os.path.join(ref, path.removeprefix(".claude/memory/"))),
                            path)


class ReadOnlyTest(_Project):
    def snapshot(self):
        out = {}
        for p in sorted(self.base.rglob("*")):
            st = os.lstat(p)
            digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
            out[p.relative_to(self.base).as_posix()] = (st.st_mode, st.st_size,
                                                       st.st_mtime_ns, digest)
        return out

    def test_nothing_is_written(self):
        self.adopt("routes.json")
        (self.memory / "INDEX.md").write_text("custom\n")
        before = self.snapshot()
        for args in ((), ("--json",), ("--verbose",)):
            self.assertEqual(0, run(self.project, *args).returncode)
        self.assertEqual(before, self.snapshot())


class LinkAndSpecialFileTest(_Project):
    def setUp(self):
        super().setUp()
        self.outside = self.base / "outside"
        self.outside.mkdir()

    def test_memory_linked_inside_the_project_is_compared(self):
        """A shared `.claude/memory` linked from elsewhere in the project must not read as missing."""
        shutil.rmtree(self.memory)
        shared = self.project / "shared-memory"
        shared.mkdir()
        shutil.copyfile(TEMPLATE_MEMORY / "routes.json", shared / "routes.json")
        self.memory.symlink_to(shared, target_is_directory=True)
        _, files = statuses(self.project)
        self.assertEqual("identical", files[mem("routes.json")]["status"])
        self.assertEqual("missing", files[mem("reflect-skip.json")]["status"])

    def test_link_escaping_the_project_is_skipped_even_for_absent_files(self):
        shutil.rmtree(self.memory)
        shutil.copyfile(TEMPLATE_MEMORY / "routes.json", self.outside / "routes.json")
        self.memory.symlink_to(self.outside, target_is_directory=True)
        data, files = statuses(self.project)
        # Present outside or not, nothing behind the link is read or called missing.
        for f in data["files"]:
            self.assertEqual(("skipped", "link_outside_project"),
                             (f["status"], f.get("reason")), f["path"])
        self.assertFalse(data["complete"])
        self.assertIn("incomplete", run(self.project).stdout)

    def test_file_link_escaping_the_project_is_skipped(self):
        target = self.outside / "routes.json"
        shutil.copyfile(TEMPLATE_MEMORY / "routes.json", target)
        (self.memory / "routes.json").symlink_to(target)
        _, files = statuses(self.project)
        self.assertEqual("link_outside_project", files[mem("routes.json")]["reason"])

    def test_broken_and_looping_ancestor_links_are_skipped_not_missing(self):
        (self.memory / "decisions").symlink_to(self.project / "nowhere",
                                               target_is_directory=True)
        (self.memory / "patterns").symlink_to(self.memory / "patterns")
        _, files = statuses(self.project)
        self.assertEqual(("skipped", "broken_link"),
                         (files[mem("decisions/README.md")]["status"],
                          files[mem("decisions/README.md")]["reason"]))
        self.assertEqual(("skipped", "link_loop"),
                         (files[mem("patterns/code-quality.md")]["status"],
                          files[mem("patterns/code-quality.md")]["reason"]))

    def test_link_through_a_file_is_not_a_directory(self):
        """A link target that runs through a regular file must not be reported as a loop."""
        self.adopt("routes.json")
        (self.memory / "decisions").symlink_to(self.memory / "routes.json" / "x")
        _, files = statuses(self.project)
        self.assertEqual(("skipped", "not_a_directory"),
                         (files[mem("decisions/README.md")]["status"],
                          files[mem("decisions/README.md")]["reason"]))

    def test_non_regular_files_and_ancestors_are_skipped(self):
        (self.memory / "patterns").write_text("a file where a directory is expected\n")
        (self.memory / "routes.json").mkdir()
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.memory / "reflect-skip.json")
        _, files = statuses(self.project)
        self.assertEqual("not_a_directory", files[mem("patterns/code-quality.md")]["reason"])
        self.assertEqual("not_a_regular_file", files[mem("routes.json")]["reason"])
        if hasattr(os, "mkfifo"):
            self.assertEqual("not_a_regular_file", files[mem("reflect-skip.json")]["reason"])


class ArgumentAndReferenceTest(_Project):
    def test_findings_exit_zero(self):
        self.assertEqual(0, run(self.project).returncode)

    def test_project_dir_must_be_given_and_absolute(self):
        self.assertEqual(2, run(None).returncode)
        self.assertEqual(2, run("relative/project", cwd=self.base).returncode)
        self.assertEqual(2, run("").returncode)

    def test_absent_or_non_directory_project_fails(self):
        self.assertEqual(1, run(self.base / "absent").returncode)
        not_dir = self.base / "file"
        not_dir.write_text("x")
        self.assertEqual(1, run(not_dir).returncode)

    def test_unusable_reference_fails_instead_of_reporting_success(self):
        empty = self.base / "empty-ref"
        empty.mkdir()
        self.assertEqual(1, run(self.project, reference=empty).returncode)
        self.assertEqual(1, run(self.project, reference=self.base / "absent-ref").returncode)
        linked = self.base / "linked-ref"
        shutil.copytree(TEMPLATE_MEMORY, linked)
        (linked / "extra.md").symlink_to(TEMPLATE_MEMORY / "routes.json")
        self.assertEqual(1, run(self.project, reference=linked).returncode)


class PackagingTest(unittest.TestCase):
    def test_both_adapters_ship_the_same_reference_including_dotfiles(self):
        expected = tree_files(TEMPLATE_MEMORY)
        self.assertIn(".gitignore", expected)
        for ref in ADAPTER_REFERENCES:
            with self.subTest(ref=str(ref.relative_to(ROOT))):
                self.assertEqual(expected, tree_files(ref), "run ./build.sh")
                for rel in expected:
                    self.assertEqual((TEMPLATE_MEMORY / rel).read_bytes(),
                                     (ref / rel).read_bytes(), rel)

    def test_only_the_memory_subset_ships(self):
        for ref in ADAPTER_REFERENCES:
            for name in ("AGENTS.md", "CLAUDE.md", ".github"):
                self.assertFalse((ref / name).exists(), f"{ref}: {name}")

    def test_codex_skill_bundles_only_its_own_script(self):
        scripts = CODEX_SKILL / "scripts"
        self.assertEqual({"template_check.py", "template-reference"},
                         {p.name for p in scripts.iterdir() if p.name != "__pycache__"})
        self.assertEqual(SCRIPT.read_bytes(), (scripts / "template_check.py").read_bytes())
        self.assertEqual(SCRIPT.read_bytes(), (CLAUDE_BIN / "agent-template-check").read_bytes())


@unittest.skipUnless(shutil.which("git"), "git is required")
class InstalledOutsideRepositoryTest(unittest.TestCase):
    """Each adapter runs from a plugin-cache-like copy outside this repository, against a linked
    worktree whose primary checkout has a file the worktree lacks. The result must describe the
    named worktree — never the primary checkout, the working directory, or this repository."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = pathlib.Path(tmp.name).resolve()
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@t")
        git = lambda *a, cwd: subprocess.run(["git", *a], cwd=cwd, env=env, check=True,
                                             capture_output=True)
        self.primary = base / "primary"
        self.primary.mkdir()
        git("init", "-q", cwd=self.primary)
        (self.primary / "README.md").write_text("x\n")
        git("add", ".", cwd=self.primary)
        git("commit", "-qm", "init", cwd=self.primary)
        self.worktree = base / "worktree"
        git("worktree", "add", "-q", "-b", "wt", str(self.worktree), cwd=self.primary)
        memory = self.primary / ".claude" / "memory"
        memory.mkdir(parents=True)
        shutil.copyfile(TEMPLATE_MEMORY / "reflect-skip.json", memory / "reflect-skip.json")

        self.cache = base / "plugin-cache"
        shutil.copytree(CLAUDE_BIN, self.cache / "harness" / "bin")
        shutil.copytree(CODEX_SKILL, self.cache / "codex" / "template-check")

    def check(self, script, cwd):
        for project, expected in ((self.worktree, "missing"), (self.primary, "identical")):
            result = run(project, "--json", script=script, reference=None, cwd=cwd)
            self.assertEqual(0, result.returncode, result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data["reference_dir"].startswith(str(self.cache)),
                            "the bundled reference must come from the installed copy")
            files = {f["path"]: f["status"] for f in data["files"]}
            self.assertEqual(expected, files[mem("reflect-skip.json")], project)

    def test_claude_bin_from_an_unrelated_cwd(self):
        self.check(self.cache / "harness" / "bin" / "agent-template-check", cwd=self.primary)

    def test_codex_skill_from_its_skill_directory(self):
        skill = self.cache / "codex" / "template-check"
        self.check(skill / "scripts" / "template_check.py", cwd=skill)


if __name__ == "__main__":
    unittest.main()
