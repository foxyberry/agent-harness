import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "project-template"


class ProjectTemplateTest(unittest.TestCase):
    def test_runtime_files_are_ignored_but_approved_memory_is_trackable(self):
        self.assertFalse((TEMPLATE / ".gitignore").exists())

        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp)
            shutil.copytree(TEMPLATE, project, dirs_exist_ok=True)
            git_env = os.environ.copy()
            git_env["GIT_CONFIG_GLOBAL"] = os.devnull
            git_env["GIT_CONFIG_NOSYSTEM"] = "1"
            subprocess.run(
                ["git", "init", "-q"], cwd=project, check=True, env=git_env
            )

            pending = project / ".claude" / "memory" / "_pending" / "draft.md"
            pending_decision = (
                project
                / ".claude"
                / "memory"
                / "_pending"
                / "decisions"
                / "draft.md"
            )
            approved = project / ".claude" / "memory" / "approved.md"
            decision = project / ".claude" / "memory" / "decisions" / "approved.md"
            reflect_log = project / ".claude" / ".cache" / "reflect.log"
            review_ledger = (
                project / ".claude" / ".cache" / "review-ledger" / "pr-123.json"
            )
            pending_decision.parent.mkdir(parents=True, exist_ok=True)
            review_ledger.parent.mkdir(parents=True, exist_ok=True)
            pending.write_text("unreviewed\n")
            pending_decision.write_text("unreviewed decision\n")
            approved.write_text("approved\n")
            decision.write_text("approved decision\n")
            reflect_log.write_text("local reflection output\n")
            review_ledger.write_text("{}\n")

            status = subprocess.run(
                ["git", "status", "--short", "--untracked-files=all"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
                env=git_env,
            ).stdout
            ignored_by = subprocess.run(
                ["git", "check-ignore", "-v", str(pending.relative_to(project))],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
                env=git_env,
            ).stdout
            cache_ignored_by = subprocess.run(
                [
                    "git",
                    "check-ignore",
                    "-v",
                    str(reflect_log.relative_to(project)),
                ],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
                env=git_env,
            ).stdout

            self.assertNotIn("_pending/draft.md", status)
            self.assertNotIn("_pending/decisions/draft.md", status)
            self.assertNotIn(".claude/.cache/reflect.log", status)
            self.assertNotIn(".claude/.cache/review-ledger/pr-123.json", status)
            self.assertIn(".claude/memory/approved.md", status)
            self.assertIn(".claude/memory/decisions/approved.md", status)
            self.assertIn(".claude/.gitignore", status)
            self.assertIn(".claude/memory/.gitignore", status)
            self.assertIn(".claude/memory/.gitignore:", ignored_by)
            self.assertIn(":_pending/", ignored_by)
            self.assertIn(".claude/.gitignore:", cache_ignored_by)
            self.assertIn(":.cache/", cache_ignored_by)
