import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "core" / "scripts" / "verify_regression.py"
sys.path.insert(0, str(SCRIPT.parent))

import verify_regression  # noqa: E402


class VerifyRegressionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        subprocess.run(["git", "init", "-q", "-b", "feature"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.root, check=True)
        (self.root / "behavior.py").write_text("VALUE = False\n")
        subprocess.run(["git", "add", "behavior.py"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.root, check=True)
        (self.root / "behavior.py").write_text("VALUE = True\n")
        (self.root / "regression_test.py").write_text(
            "from behavior import VALUE\nraise SystemExit(0 if VALUE else 1)\n"
        )
        (self.root / "guard_test.py").write_text("raise SystemExit(0)\n")

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *tests, extra=None, check=True):
        command = [
            sys.executable, str(SCRIPT), "--project-dir", str(self.root),
            "--source", "behavior.py", "--base", "HEAD",
            "--command", f"{sys.executable} {{test}}",
        ]
        command.extend(extra or [])
        command.extend(tests)
        return subprocess.run(command, text=True, capture_output=True, check=check)

    def test_classifies_each_test_and_preserves_worktree(self):
        before = subprocess.run(
            ["git", "status", "--porcelain=v1", "-uall"],
            cwd=self.root, text=True, capture_output=True, check=True,
        ).stdout

        result = self.run_cli("regression_test.py", "guard_test.py")

        after = subprocess.run(
            ["git", "status", "--porcelain=v1", "-uall"],
            cwd=self.root, text=True, capture_output=True, check=True,
        ).stdout
        self.assertIn("regression test (catches bug)", result.stdout)
        self.assertIn("not regression (new-logic guard)", result.stdout)
        self.assertIn("Original worktree unchanged: yes", result.stdout)
        self.assertEqual(before, after)
        worktrees = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self.root, text=True, capture_output=True, check=True,
        ).stdout
        self.assertEqual(worktrees.count("worktree "), 1)

    def test_requires_test_placeholder(self):
        result = self.run_cli(
            "guard_test.py",
            extra=["--command", f"{sys.executable} guard_test.py"],
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("{test}", result.stderr)

    def test_rejects_source_outside_project(self):
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--project-dir", str(self.root),
                "--source", "../outside.py", "--base", "HEAD",
                "--command", f"{sys.executable} {{test}}", "guard_test.py",
            ],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("상위 경로", result.stderr)

    def test_command_start_failure_still_removes_temporary_worktree(self):
        result = self.run_cli(
            "guard_test.py",
            extra=["--command", "definitely-not-installed-{test}"],
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        worktrees = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self.root, text=True, capture_output=True, check=True,
        ).stdout
        self.assertEqual(worktrees.count("worktree "), 1)

    def test_runner_error_is_inconclusive_not_regression(self):
        result = self.run_cli("missing_test.py", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("inconclusive (test path missing)", result.stdout)
        self.assertNotIn("regression test (catches bug)", result.stdout)

    def test_untracked_implementation_is_available_to_fixed_baseline(self):
        (self.root / "newfeature.py").write_text("READY = True\n")
        (self.root / "newfeature_test.py").write_text(
            "from behavior import VALUE\nfrom newfeature import READY\n"
            "raise SystemExit(0 if VALUE and READY else 1)\n"
        )
        result = self.run_cli(
            "newfeature_test.py", extra=["--source", "newfeature.py"]
        )
        self.assertIn("regression test (catches bug)", result.stdout)
        self.assertNotIn("fixed baseline failed", result.stdout)

    def test_merge_base_default_path(self):
        subprocess.run(["git", "branch", "main", "HEAD"], cwd=self.root, check=True)
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--project-dir", str(self.root),
                "--source", "behavior.py", "--base-ref", "main",
                "--command", f"{sys.executable} {{test}}", "regression_test.py",
            ],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("regression test (catches bug)", result.stdout)

    def test_timeout_is_inconclusive_and_json_uses_null_exit(self):
        (self.root / "slow_test.py").write_text(
            "import time\ntime.sleep(2)\n"
        )
        result = self.run_cli(
            "slow_test.py", extra=["--timeout", "1", "--json"], check=False
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn('"classification": "inconclusive (fixed baseline failed)"', result.stdout)
        self.assertIn('"exit_code": null', result.stdout)

    def test_locked_worktree_is_unlocked_and_removed(self):
        path = self.root / ".claude" / ".cache" / "locked-worktree"
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(path), "HEAD"],
            cwd=self.root, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "worktree", "lock", str(path)],
            cwd=self.root, check=True,
        )

        warning = verify_regression.remove_worktree(self.root, path)

        self.assertEqual(warning, "")
        self.assertFalse(path.exists())
        worktrees = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self.root, text=True, capture_output=True, check=True,
        ).stdout
        self.assertEqual(worktrees.count("worktree "), 1)


if __name__ == "__main__":
    unittest.main()
