import builtins
import importlib.util
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "core" / "hooks" / "pr-merge-reflect.py"
SPEC = importlib.util.spec_from_file_location("pr_merge_reflect", SCRIPT)
pr_merge_reflect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pr_merge_reflect)


class PrMergeReflectTest(unittest.TestCase):
    def test_cache_exclude_is_added_once_without_tracked_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            exclude = pathlib.Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "info/exclude"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            )
            if not exclude.is_absolute():
                exclude = root / exclude
            exclude.write_text("# keep existing rule")

            pr_merge_reflect._ensure_local_cache_exclude(str(root))
            pr_merge_reflect._ensure_local_cache_exclude(str(root))

            lines = exclude.read_text().splitlines()
            self.assertIn("# keep existing rule", lines)
            self.assertEqual(lines.count(".claude/.cache/"), 1)
            self.assertFalse((root / ".gitignore").exists())
            ignored = subprocess.run(
                ["git", "check-ignore", ".claude/.cache/reflect.log"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(ignored.returncode, 0)

    def test_linked_worktree_uses_git_resolved_exclude(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            root = base / "root"
            worktree = base / "worktree"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=root, check=True
            )
            (root / "tracked.txt").write_text("tracked\n")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "initial"], cwd=root, check=True
            )
            subprocess.run(
                ["git", "worktree", "add", "-q", str(worktree), "-b", "feature"],
                cwd=root,
                check=True,
            )

            pr_merge_reflect._ensure_local_cache_exclude(str(worktree))

            ignored = subprocess.run(
                ["git", "check-ignore", ".claude/.cache/reflect.log"],
                cwd=worktree,
                capture_output=True,
                text=True,
            )
            self.assertEqual(ignored.returncode, 0)

    def test_monorepo_subdirectory_uses_repo_relative_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project = root / "packages" / "api"
            project.mkdir(parents=True)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)

            pr_merge_reflect._ensure_local_cache_exclude(str(project))

            ignored = subprocess.run(
                ["git", "check-ignore", "packages/api/.claude/.cache/reflect.log"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(ignored.returncode, 0)
            exclude = root / ".git" / "info" / "exclude"
            self.assertIn("packages/api/.claude/.cache/", exclude.read_text().splitlines())

    def test_non_git_project_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            pr_merge_reflect._ensure_local_cache_exclude(tmp)
            self.assertEqual(list(pathlib.Path(tmp).iterdir()), [])

    def test_permission_error_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            exclude = root / ".git" / "info" / "exclude"
            before = exclude.read_text()
            real_open = builtins.open

            def deny_exclude(path, *args, **kwargs):
                if str(path).endswith("info/exclude"):
                    raise PermissionError("read-only")
                return real_open(path, *args, **kwargs)

            with patch("builtins.open", side_effect=deny_exclude):
                pr_merge_reflect._ensure_local_cache_exclude(str(root))
            self.assertEqual(exclude.read_text(), before)
