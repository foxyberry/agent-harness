import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "core" / "scripts" / "review_ledger.py"
sys.path.insert(0, str(SCRIPT.parent))

import review_ledger  # noqa: E402
import handoff  # noqa: E402


class ReviewLedgerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        subprocess.run(["git", "init", "-q", "-b", "feature"], cwd=self.root, check=True)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, check=True):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--project-dir", str(self.root), *args],
            text=True,
            capture_output=True,
            check=check,
        )

    def test_lifecycle_and_stable_markdown(self):
        self.run_cli("init", "--pr", "123")
        self.run_cli(
            "reviewer", "--pr", "123", "--name", "Claude", "--thread", "thread-1"
        )
        finding_id = self.run_cli(
            "add", "--pr", "123", "--severity", "P2", "--file", "src/a.ts",
            "--line", "42", "--claim", "ready is stale",
            "--evidence", "rg -n setReady src/a.ts",
            "--reviewer", "Claude", "--thread", "thread-1",
        ).stdout.strip()
        self.assertEqual(finding_id, "F-001")

        before = self.run_cli("show", "--pr", "123").stdout
        self.assertIn("### Open", before)
        self.assertIn("F-001", before)
        self.assertIn("Claude (`thread-1`)", before)
        self.assertIn("Claude / `thread-1`", before)

        self.run_cli(
            "update", "--pr", "123", "F-001", "--status", "fixed",
            "--evidence", "pytest tests/test_a.py",
        )
        after = self.run_cli("show", "--pr", "123").stdout
        self.assertIn("### Resolved", after)
        self.assertIn("pytest tests/test_a.py", after)
        self.assertIn("Round 1: new 1 / fixed 1", after)

    def test_absence_claim_requires_evidence(self):
        self.run_cli("init", "--pr", "123")
        result = self.run_cli(
            "add", "--pr", "123", "--severity", "P2",
            "--claim", "test does not exist", "--absence",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--evidence", result.stderr)

    def test_invalid_scopes_do_not_overwrite_existing_ledger(self):
        self.run_cli("init", "--pr", "123")
        result = self.run_cli("init", "--pr", "123", check=False)
        self.assertEqual(result.returncode, 2)
        data = json.loads(review_ledger.ledger_path(self.root, 123).read_text())
        self.assertEqual(data["pr"], 123)

    def test_round_increments(self):
        self.run_cli("init", "--pr", "123")
        self.assertEqual(self.run_cli("round", "--pr", "123").stdout.strip(), "2")
        self.run_cli(
            "add", "--pr", "123", "--severity", "P3", "--claim", "new in round 2"
        )
        report = self.run_cli("show", "--pr", "123").stdout
        self.assertIn("Round 2: new 1", report)

    def test_handoff_summary_carries_open_findings_and_thread(self):
        self.run_cli("init", "--pr", "123")
        self.run_cli(
            "reviewer", "--pr", "123", "--name", "Claude", "--thread", "thread-1"
        )
        self.run_cli(
            "add", "--pr", "123", "--severity", "P1", "--file", "src/a.ts",
            "--line", "7", "--claim", "race remains",
            "--reviewer", "Codex", "--thread", "codex-thread",
        )

        summary = handoff._review_ledger_summary(str(self.root), "feature")

        self.assertIn("PR #123", summary)
        self.assertIn("thread `thread-1`", summary)
        self.assertIn("F-001 [P1] src/a.ts:7", summary)
        self.assertIn("Codex thread `codex-thread`", summary)

    def test_handoff_uses_latest_ledger_for_same_branch(self):
        self.run_cli("init", "--pr", "123")
        first = review_ledger.load_ledger(self.root, 123)
        first["updated_at"] = "2026-01-01T00:00:00+00:00"
        review_ledger.save_ledger(self.root, first)
        self.run_cli("init", "--pr", "124")

        summary = handoff._review_ledger_summary(str(self.root), "feature")

        self.assertIn("PR #124", summary)


if __name__ == "__main__":
    unittest.main()
