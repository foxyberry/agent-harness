import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "project-template"


class ProjectTemplateTest(unittest.TestCase):
    def test_pending_drafts_are_ignored_but_approved_memory_is_trackable(self):
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
            pending_decision.parent.mkdir(parents=True, exist_ok=True)
            pending.write_text("unreviewed\n")
            pending_decision.write_text("unreviewed decision\n")
            approved.write_text("approved\n")
            decision.write_text("approved decision\n")

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

            self.assertNotIn("_pending/draft.md", status)
            self.assertNotIn("_pending/decisions/draft.md", status)
            self.assertIn(".claude/memory/approved.md", status)
            self.assertIn(".claude/memory/decisions/approved.md", status)
            self.assertIn(".claude/memory/.gitignore", status)
            self.assertIn(".claude/memory/.gitignore:1:_pending/", ignored_by)
