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
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)

            pending = project / ".claude" / "memory" / "_pending" / "draft.md"
            approved = project / ".claude" / "memory" / "approved.md"
            decision = project / ".claude" / "memory" / "decisions" / "approved.md"
            pending.parent.mkdir(parents=True)
            pending.write_text("unreviewed\n")
            approved.write_text("approved\n")
            decision.write_text("approved decision\n")

            status = subprocess.run(
                ["git", "status", "--short", "--untracked-files=all"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
            ).stdout

            self.assertNotIn("_pending/draft.md", status)
            self.assertIn(".claude/memory/approved.md", status)
            self.assertIn(".claude/memory/decisions/approved.md", status)
            self.assertIn(".claude/memory/.gitignore", status)
