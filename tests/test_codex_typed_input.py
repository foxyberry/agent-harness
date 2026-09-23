"""Codex rollout `role: "user"` items: keep what the person typed, drop what an agent injected.

The shapes below are copied from real rollouts written by Codex 0.153.4 and 0.154.0. Those logs
carry no `event_msg.user_message` record at all, so before this path every Codex retrospective
read nothing (#147).
"""
import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = {
    "core": ROOT / "core" / "hooks" / "compact_transcript.py",
    "claude-adapter": ROOT / "plugins" / "harness" / "hooks" / "compact_transcript.py",
    "codex-adapter": ROOT / "plugins" / "codex" / "skills" / "feedback-review" / "scripts"
                     / "compact_transcript.py",
}

TUI_META = {"type": "session_meta", "payload": {
    "originator": "codex-tui", "source": "cli", "cli_version": "0.154.0"}}
EXEC_META = {"type": "session_meta", "payload": {
    "originator": "codex_exec", "source": "exec", "cli_version": "0.154.0"}}
SUBAGENT_META = {"type": "session_meta", "payload": {
    "originator": "codex-tui", "cli_version": "0.154.0", "thread_source": "subagent",
    "source": {"subagent": {"thread_spawn": {"depth": 1}}}}}


def _user_item(text, kinds):
    """A `response_item` message carrying one text block and the given content_item_kinds."""
    payload = {"type": "message", "role": "user",
               "content": [{"type": "input_text", "text": text}]}
    if kinds is not None:
        payload["internal_chat_message_metadata_passthrough"] = {
            "turn_id": "t1", "create_time": 1.0, "content_item_kinds": kinds}
    return {"type": "response_item", "payload": payload}


class CodexTypedInputTest(unittest.TestCase):
    def _load(self, name):
        spec = importlib.util.spec_from_file_location(f"compact_{name}", SOURCES[name])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _compact(self, mod, records, strict=True):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            path = fh.name
        try:
            out, _ = mod.compact(path, require_attributed_user=strict)
            return out
        finally:
            pathlib.Path(path).unlink()

    def test_typed_item_is_kept_and_injections_are_dropped(self):
        records = [
            TUI_META,
            _user_item("# AGENTS.md instructions for /repo\n<INSTRUCTIONS>rules</INSTRUCTIONS>",
                       ["agents_md.instructions", "environments.environment_context"]),
            _user_item("<environment_context><cwd>/repo</cwd></environment_context>",
                       ["environments.environment_context"]),
            _user_item("<recommended_plugins>a plugin</recommended_plugins>",
                       ["plugins.recommendations", "agents_md.instructions"]),
            _user_item("<user_action><context>review task</context></user_action>", ["unknown"]),
            _user_item("머지했어", ["user.text"]),
        ]
        for name in SOURCES:
            with self.subTest(source=name):
                out = self._compact(self._load(name), records)
                self.assertIn("머지했어", out)
                for leaked in ("AGENTS.md instructions", "environment_context",
                               "recommended_plugins", "user_action"):
                    self.assertNotIn(leaked, out)

    def test_attachment_message_is_typed_despite_its_image_placeholder(self):
        # A message with an attachment lists kinds several times and its first text block is the
        # placeholder Codex writes for the file. It is still something the person typed.
        records = [TUI_META,
                   _user_item('<image name=[Image #1] path="/tmp/a.png"/>\n이거 확인해줘',
                              ["user.text", "user.image", "user.text", "user.text"])]
        for name in SOURCES:
            with self.subTest(source=name):
                self.assertIn("이거 확인해줘", self._compact(self._load(name), records))

    def test_agent_written_sessions_are_not_read_as_user_input(self):
        # `codex exec` carries the prompt a delegating agent wrote, and a subagent thread carries
        # the prompt its parent wrote. Both land in the same `user.text` slot.
        for meta, label in ((EXEC_META, "exec"), (SUBAGENT_META, "subagent")):
            records = [meta, _user_item("Review the current code changes.", ["user.text"])]
            for name in SOURCES:
                with self.subTest(source=name, session=label):
                    self.assertEqual("", self._compact(self._load(name), records))

    def test_logs_without_the_kinds_field_are_unchanged(self):
        # Codex 0.148.0 and older write no content_item_kinds, so nothing separates a typed item
        # from an injected one. Those items stay unread rather than being guessed at.
        records = [TUI_META, _user_item("오래된 로그의 발언", None)]
        for name in SOURCES:
            with self.subTest(source=name):
                self.assertEqual("", self._compact(self._load(name), records))

    def test_recovery_mode_also_shows_typed_input(self):
        records = [TUI_META,
                   _user_item("<environment_context>ctx</environment_context>",
                              ["environments.environment_context"]),
                   _user_item("계속 진행해줘", ["user.text"])]
        for name in SOURCES:
            with self.subTest(source=name):
                out = self._compact(self._load(name), records, strict=False)
                self.assertIn("계속 진행해줘", out)
                self.assertNotIn("environment_context", out)

    def test_provenance_evidence_names_the_kinds_field(self):
        mod = self._load("core")
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as fh:
            for r in (TUI_META, _user_item("안녕", ["user.text"])):
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            path = fh.name
        try:
            turns = [t for t in mod.iter_turns(path) if t.role == "user"]
        finally:
            pathlib.Path(path).unlink()
        self.assertEqual([("attributed", "codex-kinds")],
                         [(t.provenance, t.evidence) for t in turns])


if __name__ == "__main__":
    unittest.main()
