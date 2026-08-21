"""트랜스크립트 파싱과 목적별 선택 정책의 경계를 검증한다."""
import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "compact_transcript_policy", ROOT / "core" / "hooks" / "compact_transcript.py")
compact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compact)


class ProvenanceClassificationTest(unittest.TestCase):
    def _turn(self, record):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            path = fh.name
        try:
            return list(compact.iter_turns(path))
        finally:
            pathlib.Path(path).unlink()

    def test_claude_provenance_evidence_is_explicit(self):
        cases = [
            ({"promptSource": "typed"}, "attributed", "promptSource"),
            ({"promptSource": "sdk"}, "nonhuman", "promptSource"),
            ({"origin": {"kind": "human"}}, "attributed", "origin"),
            ({"isMeta": True}, "nonhuman", "isMeta"),
            ({}, "unattributed", "marker"),
        ]
        for extra, provenance, evidence in cases:
            record = {"type": "user", "message": {"role": "user", "content": "plain"},
                      **extra}
            with self.subTest(extra=extra):
                turn = self._turn(record)[0]
                self.assertEqual((provenance, evidence), (turn.provenance, turn.evidence))

    def test_injected_marker_and_codex_channel_are_distinct(self):
        marker = {"type": "user", "message": {"role": "user",
                  "content": "<task-notification>injected</task-notification>"}}
        codex = {"type": "event_msg", "payload": {"type": "user_message", "message": "human"}}

        self.assertEqual(("nonhuman", "marker"),
                         (self._turn(marker)[0].provenance, self._turn(marker)[0].evidence))
        self.assertEqual(("attributed", "codex-channel"),
                         (self._turn(codex)[0].provenance, self._turn(codex)[0].evidence))

    def test_tool_result_and_codex_response_user_are_not_turns(self):
        tool_result = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "output"}]}}
        injected = {"type": "response_item", "payload": {"type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": "context"}]}}
        self.assertEqual([], self._turn(tool_result))
        self.assertEqual([], self._turn(injected))


class SelectionPolicyTest(unittest.TestCase):
    def test_nonhuman_turn_is_transparent_to_trusted_segment(self):
        turns = [
            compact.Turn("user", [("text", "human")], "attributed", "promptSource"),
            compact.Turn("user", [("text", "system")], "nonhuman", "marker"),
            compact.Turn("assistant", [("text", "reply")], None, None),
        ]

        selected = list(compact.select_attributed(turns))

        self.assertEqual(["user", "assistant"], [turn.role for turn in selected])
        self.assertEqual("reply", selected[-1].blocks[0][1])

    def test_unattributed_turn_revokes_trusted_segment(self):
        turns = [
            compact.Turn("user", [("text", "human")], "attributed", "promptSource"),
            compact.Turn("user", [("text", "unknown")], "unattributed", "marker"),
            compact.Turn("assistant", [("text", "reply")], None, None),
        ]
        self.assertEqual(["human"], [t.blocks[0][1] for t in compact.select_attributed(turns)])

    def test_explicit_automation_revokes_but_marker_notification_is_transparent(self):
        prefix = [compact.Turn("user", [("text", "human")], "attributed", "promptSource")]
        automated = prefix + [
            compact.Turn("user", [("text", "sdk")], "nonhuman", "promptSource"),
            compact.Turn("assistant", [("text", "automation reply")], None, None),
        ]
        notification = prefix + [
            compact.Turn("user", [("text", "notice")], "nonhuman", "marker"),
            compact.Turn("assistant", [("text", "human reply")], None, None),
        ]

        self.assertEqual(["human"], [t.blocks[0][1] for t in compact.select_attributed(automated)])
        self.assertEqual(["human", "human reply"],
                         [t.blocks[0][1] for t in compact.select_attributed(notification)])

    def test_render_contract_covers_truncation_and_tool_cap(self):
        tools = [("tool", f"tool-{i}") for i in range(10)]
        out = compact.render([
            compact.Turn("assistant", [("text", "x" * (compact.ASSIST_MAX + 1)), *tools],
                         None, None),
        ])
        self.assertIn(" …(절단)", out)
        self.assertIn("tool-7", out)
        self.assertNotIn("tool-8", out)
        self.assertTrue(out.endswith(" …"))

    def test_recovery_output_is_locked_by_golden_fixture(self):
        fixture = ROOT / "tests" / "fixtures" / "transcript-recovery.jsonl"
        golden = ROOT / "tests" / "fixtures" / "transcript-recovery.md"
        self.assertEqual(golden.read_text(encoding="utf-8").rstrip("\n"),
                         compact.compact(fixture)[0])


if __name__ == "__main__":
    unittest.main()
