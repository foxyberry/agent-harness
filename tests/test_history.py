import json
import pathlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "scripts"))

import handoff  # noqa: E402


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.claude = self.root / "claude.jsonl"
        self.codex = self.root / "codex.jsonl"
        self.claude.write_text(
            json.dumps({
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "fix payment retry"}],
                }
            }) + "\n"
        )
        self.codex.write_text(
            json.dumps({
                "type": "session_meta",
                "payload": {"id": "codex-1", "cwd": str(self.root)},
            }) + "\n" + json.dumps({
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "update docs"}],
                },
            }) + "\n"
        )

    def tearDown(self):
        self.temp.cleanup()

    def candidates(self):
        now = time.time()
        return (
            [(now - 20, self.claude.stat().st_size, str(self.claude))],
            [(now - 10, self.codex.stat().st_size, str(self.codex))],
        )

    def test_combines_tools_newest_first_with_resume_commands(self):
        claude, codex = self.candidates()
        with (
            patch.object(handoff, "_recent_claude_transcripts", return_value=claude),
            patch.object(handoff, "_recent_codex_rollouts", return_value=codex),
        ):
            rows = handoff._history_rows(str(self.root), limit=20, since="1d")

        self.assertEqual([row["tool"] for row in rows], ["codex", "claude"])
        self.assertEqual(rows[0]["snippet"], "update docs")
        self.assertIn("--session", rows[0]["resume_command"])
        report = handoff._render_history(str(self.root), rows)
        self.assertIn("fw", report)
        self.assertIn("--session", report)
        self.assertIn(str(self.codex), report)

    def test_grep_searches_full_jsonl_within_candidates(self):
        claude, codex = self.candidates()
        with (
            patch.object(handoff, "_recent_claude_transcripts", return_value=claude),
            patch.object(handoff, "_recent_codex_rollouts", return_value=codex),
        ):
            rows = handoff._history_rows(
                str(self.root), since="1d", grep="PAYMENT RETRY"
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tool"], "claude")

    def test_no_content_hides_prompt_but_keeps_path(self):
        claude, _codex = self.candidates()
        with patch.object(
            handoff, "_recent_claude_transcripts", return_value=claude
        ):
            rows = handoff._history_rows(
                str(self.root), from_tool="claude", since="1d", no_content=True
            )

        report = handoff._render_history(str(self.root), rows, no_content=True)
        self.assertNotIn("payment retry", report)
        self.assertNotIn("마지막 사용자 입력", report)
        self.assertIn(str(self.claude), report)

    def test_since_validation(self):
        for value in ("", "30", "0d", "-1d", "1y", "4000d"):
            with self.assertRaises(ValueError):
                handoff._parse_since(value)
        self.assertEqual(handoff._parse_since("2w"), 14 * 86400)


if __name__ == "__main__":
    unittest.main()
