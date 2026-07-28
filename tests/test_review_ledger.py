import json
import os
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
            "--claim", "test does not exist",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--evidence", result.stderr)

    def test_absence_heuristic_can_be_explicitly_overridden(self):
        self.run_cli("init", "--pr", "123")
        result = self.run_cli(
            "add", "--pr", "123", "--severity", "P3",
            "--claim", "missing UI state label", "--not-absence",
        )
        self.assertEqual(result.stdout.strip(), "F-001")

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

    def test_round_requires_open_findings_acknowledgement(self):
        self.run_cli("init", "--pr", "123")
        self.run_cli("add", "--pr", "123", "--severity", "P2", "--claim", "race")
        blocked = self.run_cli("round", "--pr", "123", check=False)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("F-001", blocked.stderr)
        allowed = self.run_cli(
            "round", "--pr", "123", "--acknowledge-open"
        )
        self.assertEqual(allowed.stdout.strip(), "2")

    def test_reopened_finding_is_counted_in_current_round_history(self):
        self.run_cli("init", "--pr", "123")
        self.run_cli("add", "--pr", "123", "--severity", "P2", "--claim", "race")
        self.run_cli("update", "--pr", "123", "F-001", "--status", "fixed")
        self.run_cli("round", "--pr", "123")
        self.run_cli("update", "--pr", "123", "F-001", "--status", "open")
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
        first_path = review_ledger.ledger_path(self.root, 123)
        os.utime(first_path, ns=(1_000_000_000, 1_000_000_000))
        self.run_cli("init", "--pr", "124")

        summary = handoff._review_ledger_summary(str(self.root), "feature")

        self.assertIn("PR #124", summary)

    def test_handoff_warns_after_branch_rename_when_only_one_ledger_exists(self):
        self.run_cli("init", "--pr", "123")
        summary = handoff._review_ledger_summary(str(self.root), "renamed")
        self.assertIn("브랜치 rename 여부 확인", summary)
        self.assertIn("PR #123", summary)

    def test_reviewer_without_thread_preserves_existing_thread(self):
        self.run_cli("init", "--pr", "123")
        self.run_cli(
            "reviewer", "--pr", "123", "--name", "Claude", "--thread", "thread-1"
        )
        self.run_cli("reviewer", "--pr", "123", "--name", "Claude")
        data = json.loads(self.run_cli("show", "--pr", "123", "--json").stdout)
        self.assertEqual(data["reviewers"][0]["thread"], "thread-1")

    def test_concurrent_adds_do_not_lose_findings_or_duplicate_ids(self):
        self.run_cli("init", "--pr", "123")
        processes = [
            subprocess.Popen(
                [
                    sys.executable, str(SCRIPT), "--project-dir", str(self.root),
                    "add", "--pr", "123", "--severity", "P2", "--claim", f"race {i}",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for i in range(8)
        ]
        results = [process.communicate() + (process.returncode,) for process in processes]
        self.assertTrue(all(returncode == 0 for _out, _err, returncode in results))
        ids = [stdout.strip() for stdout, _stderr, _returncode in results]
        self.assertEqual(len(set(ids)), 8)
        ledger = review_ledger.load_ledger(self.root, 123)
        self.assertEqual(len(ledger["findings"]), 8)

    def test_mismatched_internal_pr_is_rejected_without_new_file(self):
        self.run_cli("init", "--pr", "123")
        path = review_ledger.ledger_path(self.root, 123)
        data = json.loads(path.read_text())
        data["pr"] = 999
        path.write_text(json.dumps(data))
        result = self.run_cli(
            "add", "--pr", "123", "--severity", "P2", "--claim", "race",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertFalse(review_ledger.ledger_path(self.root, 999).exists())

    def test_init_adds_cache_to_local_git_exclude(self):
        self.run_cli("init", "--pr", "123")
        result = subprocess.run(
            ["git", "check-ignore", ".claude/.cache/review-ledger/pr-123.json"],
            cwd=self.root,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0)

    def test_multiline_claim_does_not_break_markdown_table(self):
        self.run_cli("init", "--pr", "123")
        self.run_cli(
            "add", "--pr", "123", "--severity", "P2",
            "--claim", "line one\nline two",
        )
        report = self.run_cli("show", "--pr", "123").stdout
        self.assertIn("line one<br>line two", report)


if __name__ == "__main__":
    unittest.main()
