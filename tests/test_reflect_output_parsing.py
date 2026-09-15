"""Cases where the retrospection job **silently loses** content while reading LLM output and
transcripts (raised in review).

In both cases the failure looks like "no drafts" -- indistinguishable from there having been
nothing to extract.

Note on language: the payload strings below are deliberately Korean. They are transcript *content*,
i.e. real user input, and they pin that translating the harness's own output did not start altering
the data it carries.
"""
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "core" / "hooks" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


reflect = _load("reflect", "reflect.py")
compact_transcript = _load("compact_transcript", "compact_transcript.py")

DRAFT = """---
name: lesson-one
description: one line
type: feedback
---
Body."""


class NestedFenceTest(unittest.TestCase):
    """Does a code quote inside a draft truncate the draft?

    The ADR contract requires an `Evidence` section, so code quotes are the norm, not the exception.
    If the outer fence and the inner quote are both ``` there is **no way to tell them apart** -- an
    untagged quote is character-for-character identical to a closing fence. That is why the prompt
    demands four backticks on the outside and the parser reads them.
    """

    def test_a_draft_quoting_untagged_code_survives_intact(self):
        """An untagged ``` quote -- the old parser was truncated here."""
        text = f"````\n{DRAFT}\n\n## Evidence\n```\nprint(1)\n```\nFinal sentence.\n````\n"

        drafts = reflect._split_drafts(text)

        self.assertEqual(1, len(drafts), f"the block was split apart: {drafts}")
        self.assertIn("Final sentence", drafts[0], "truncated at the inner fence")
        self.assertIn("print(1)", drafts[0], "the quoted code disappeared")

    def test_a_draft_quoting_tagged_code_survives_intact(self):
        text = f"````\n{DRAFT}\n\n```python\nprint(1)\n```\nFinal sentence.\n````\n"

        drafts = reflect._split_drafts(text)

        self.assertEqual(1, len(drafts))
        self.assertIn("Final sentence", drafts[0])

    def test_two_separate_drafts_are_still_two(self):
        """Removing the ambiguity must not glue everything together instead."""
        text = (f"````\n{DRAFT}\n````\n\nprose in between\n\n"
                f"````\n{DRAFT.replace('one', 'two')}\n````\n")

        drafts = reflect._split_drafts(text)

        self.assertEqual(2, len(drafts))
        self.assertNotIn("prose in between", drafts[0])

    def test_a_truncated_final_block_is_kept_not_dropped(self):
        """Output cut off at the token limit has no closing fence. Dropping it would be
        indistinguishable from "there was nothing to extract"."""
        text = f"````\n{DRAFT}\n\nthe last line is cut off"

        drafts = reflect._split_drafts(text)

        self.assertEqual(1, len(drafts), "the truncated draft was discarded wholesale")
        self.assertIn("lesson-one", drafts[0])

    def test_old_three_tick_output_still_parses(self):
        """The model may drift from the instruction and emit three backticks. No draft is lost
        in that case either."""
        text = f"```\n{DRAFT}\n```\n"

        self.assertEqual(1, len(reflect._split_drafts(text)))

    def test_known_limit_three_tick_outer_with_nested_quote_is_ambiguous(self):
        """**Nails down a deliberate limit.**

        With a three-backtick outer fence, an untagged inner quote and the closing fence are the same
        string, so they are indistinguishable in principle. That is why this was solved **by contract
        (four backticks)** rather than by making the parser cleverer. If this test breaks, somebody
        tried to fix the fallback path by guessing -- re-evaluate then.
        """
        text = f"```\n{DRAFT}\n\n```\nprint(1)\n```\nFinal sentence.\n```\n"

        drafts = reflect._split_drafts(text)

        self.assertEqual(1, len(drafts))
        self.assertNotIn("Final sentence", drafts[0],
                         "the fallback path suddenly became accurate — needs review")

    def test_garbage_without_the_required_markers_is_still_dropped(self):
        """Rescuing content and accepting anything are different things."""
        self.assertEqual([], reflect._split_drafts("````\njust prose\n````\n"))
        self.assertEqual([], reflect._split_drafts("````\nunclosed prose"))


class CodexUserMessageTest(unittest.TestCase):
    """Does a Codex rollout's **injected context** get read as a user utterance?

    Codex puts its own injections into `response_item` with `role: "user"` too -- `<user_action>`
    wrappers, environment info, the project's AGENTS.md body. Measured across 8 sessions, 8 of 17
    such items were injections.

    Using them as retrospection material is fatal. If the whole of AGENTS.md enters as "what the
    user said", the retrospective extracts it as a new lesson and files it for promotion -- **the
    existing rules disguise themselves as user feedback and self-replicate.**
    """

    def _rollout(self, records):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            return fh.name

    def _compact(self, records):
        path = self._rollout(records)
        try:
            return compact_transcript.compact(path)[0]
        finally:
            pathlib.Path(path).unlink()

    INJECTED = {"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text",
                             "text": "<user_action><context>주입된 지시</context></user_action>"}]}}
    REAL = {"type": "event_msg", "payload": {"type": "user_message",
            "message": "진짜 사용자 발화다"}}
    ASSISTANT = {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "어시스턴트 답변"}]}}
    DEVELOPER = {"type": "response_item", "payload": {"type": "message", "role": "developer",
                 "content": [{"type": "input_text", "text": "시스템 지시문"}]}}

    def test_injected_context_is_not_treated_as_user_feedback(self):
        out = self._compact([self.INJECTED, self.REAL])

        self.assertIn("진짜 사용자 발화다", out)
        self.assertNotIn("주입된 지시", out, "injected context entered as a user utterance")

    def test_developer_instructions_are_not_feedback_either(self):
        out = self._compact([self.DEVELOPER, self.REAL])

        self.assertNotIn("시스템 지시문", out)

    def test_assistant_text_still_survives(self):
        """Filtering injections must not take the replies with it, or the retrospective never sees
        the conclusions."""
        out = self._compact([self.REAL, self.ASSISTANT])

        self.assertIn("진짜 사용자 발화다", out)
        self.assertIn("어시스턴트 답변", out)

    def test_claude_real_turns_survive(self):
        """This is the primary use case. Killing real utterances while filtering kills the
        retrospective itself."""
        out = self._compact([
            {"type": "user", "message": {"role": "user", "content": "클로드 발화"}},
            {"type": "assistant", "message": {"role": "assistant",
                                              "content": [{"type": "text", "text": "클로드 답변"}]}},
        ])

        self.assertIn("클로드 발화", out)
        self.assertIn("클로드 답변", out)


class ClaudeInjectedTurnTest(unittest.TestCase):
    """On the Claude side too, injections arrive in the `role: "user"` slot -- the same family as
    Codex.

    The previous version of this test pinned "Claude user text survives **unfiltered**", i.e. it was
    nailing down the defective behaviour as correct. Measured: 6 of 9 USER blocks in one transcript
    were injections, and among them was a **skill body** -- the harness's own rules disguised as a
    user utterance.
    """

    def _compact(self, records):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            path = fh.name
        try:
            return compact_transcript.compact(path)[0]
        finally:
            pathlib.Path(path).unlink()

    def _user(self, text, **extra):
        return dict({"type": "user", "message": {"role": "user", "content": text}}, **extra)

    HUMAN = {"origin": {"kind": "human", "promptSource": "typed"}}

    def test_origin_marks_who_typed_it(self):
        """Recent transcripts carry origin. When it is there, trust it."""
        out = self._compact([
            self._user("사람이 친 말", **self.HUMAN),
            self._user("도구가 넣은 것", origin={"kind": "task-notification"}),
        ])

        self.assertIn("사람이 친 말", out)
        self.assertNotIn("도구가 넣은 것", out, "a tool-inserted turn survived")

    def test_prompt_source_is_read_from_the_record_not_from_origin(self):
        """`promptSource` lives at the record top level. Reading it inside origin is a dead
        condition (measured: `origin.promptSource` was None in all 2616 records)."""
        out = self._compact([
            self._user("사람이 친 말", promptSource="typed"),
            self._user("자동화가 넣은 평문 프롬프트", promptSource="sdk"),
            self._user("시스템이 넣은 평문", promptSource="system"),
        ])

        self.assertIn("사람이 친 말", out)
        self.assertNotIn("자동화가 넣은 평문 프롬프트", out,
                         "an SDK prompt entered as user feedback")
        self.assertNotIn("시스템이 넣은 평문", out)

    def test_machine_prompts_without_a_tag_are_still_caught(self):
        """A family the marker fallback cannot catch -- it is plain text, so there is no tag.
        There is no origin either (measured: 40 sdk records), so promptSource is the only signal."""
        out = self._compact([self._user("이 PR 을 리뷰해주세요", promptSource="sdk")])

        self.assertNotIn("리뷰해주세요", out)

    def test_meta_records_are_dropped(self):
        self.assertNotIn("메타", self._compact([self._user("메타 레코드", isMeta=True)]))

    def test_old_records_without_origin_fall_back_to_markers(self):
        """Files predating origin are far more numerous (40 of this project's 46). Filtering
        strictly yields zero user utterances in them, indistinguishable from "nothing to reflect
        on"."""
        out = self._compact([
            self._user("옛 파일의 진짜 발화"),
            self._user("<task-notification>\n작업 알림 본문"),
            self._user("Base directory for this skill: /x/skills/feedback-review\n스킬 규칙 본문"),
            self._user("<local-command-caveat>Caveat: ...</local-command-caveat>"),
        ])

        self.assertIn("옛 파일의 진짜 발화", out)
        self.assertNotIn("작업 알림 본문", out)
        self.assertNotIn("스킬 규칙 본문", out, "a skill body entered as a user utterance")
        self.assertNotIn("Caveat", out)

    def test_whole_injected_families_are_filtered_not_just_the_tags_i_thought_of(self):
        """Listing tags one by one guarantees missing some.

        The first version listed only `<command-name>` and missed `<command-message>` -- 6 of those
        were in the measured corpus. Variants of the same family keep appearing, so we match on the
        **family prefix**.
        """
        families = [
            "<command-name>/plugin</command-name>",
            "<command-message>plugin</command-message>",
            "<command-args>x</command-args>",
            "<local-command-stdout>출력</local-command-stdout>",
            "<local-command-stderr>에러</local-command-stderr>",
            "<bash-input>ls -la</bash-input>",
            "<bash-stdout>파일 목록</bash-stdout>",
        ]
        out = self._compact([self._user(t + "\n주입된 본문 " + str(i))
                             for i, t in enumerate(families)] + [self._user("진짜 발화")])

        self.assertIn("진짜 발화", out)
        for i, t in enumerate(families):
            with self.subTest(family=t[:20]):
                self.assertNotIn(f"주입된 본문 {i}", out,
                                 "an injected body from this tag family survived")

    def test_talking_about_a_marker_is_not_injection(self):
        """A normal utterance that merely **mentions** a marker must not be killed -- which is why
        only the head is inspected."""
        out = self._compact([
            self._user("압축기가 <task-notification> 을 왜 거르는지 설명해줘"),
        ])

        self.assertIn("왜 거르는지", out)

    def test_the_fallback_announces_itself(self):
        """The fallback is weaker than origin-based selection. Degrading silently is exactly this
        repository's failure mode."""
        import contextlib, io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self._compact([self._user("origin 없는 발화")])

        self.assertIn("fell back to markers", err.getvalue())

    def test_no_fallback_notice_when_origin_is_present(self):
        """With a signal present the warning must not appear -- one that fires every time is read by
        nobody."""
        import contextlib, io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self._compact([self._user("사람이 친 말", **self.HUMAN)])

        self.assertNotIn("fell back to markers", err.getvalue())

    def test_retrospective_mode_refuses_unattributed_user_turns(self):
        """Recovery may use the fallback, but memory candidates are never built from turns of
        unknown origin."""
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(json.dumps(self._user("옛 파일의 진짜 발화"), ensure_ascii=False) + "\n")
            path = fh.name
        try:
            body, _ = compact_transcript.compact(path, require_attributed_user=True)
        finally:
            pathlib.Path(path).unlink()

        self.assertEqual("", body)

    def test_retrospective_mode_accepts_positively_attributed_turns(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(json.dumps(self._user("사람이 친 말", promptSource="typed"),
                                ensure_ascii=False) + "\n")
            path = fh.name
        try:
            body, _ = compact_transcript.compact(path, require_attributed_user=True)
        finally:
            pathlib.Path(path).unlink()

        self.assertIn("사람이 친 말", body)

    def test_attributed_turn_survives_injected_marker_in_the_same_file(self):
        """Real files mix human turns with command injections. Rejecting per file is wrong."""
        records = [
            self._user("사람이 친 말", promptSource="typed"),
            self._user("<command-name>/model</command-name>"),
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            path = fh.name
        try:
            body, _ = compact_transcript.compact(path, require_attributed_user=True)
        finally:
            pathlib.Path(path).unlink()

        self.assertIn("사람이 친 말", body)
        self.assertNotIn("command-name", body)

    def test_unattributed_turn_and_its_assistant_segment_are_dropped(self):
        records = [
            self._user("사람이 친 말", promptSource="typed"),
            {"type": "assistant", "message": {"role": "assistant", "content": "신뢰 구간 응답"}},
            self._user("출처 불명 턴"),
            {"type": "assistant", "message": {"role": "assistant", "content": "불명 구간 응답"}},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            path = fh.name
        try:
            body, _ = compact_transcript.compact(path, require_attributed_user=True)
        finally:
            pathlib.Path(path).unlink()

        self.assertIn("사람이 친 말", body)
        self.assertIn("신뢰 구간 응답", body)
        self.assertNotIn("출처 불명 턴", body)
        self.assertNotIn("불명 구간 응답", body)

    def test_tool_results_do_not_make_an_attributed_session_untrusted(self):
        records = [
            self._user("사람이 친 말", promptSource="typed"),
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "도구 출력"},
            ]}},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            path = fh.name
        try:
            body, _ = compact_transcript.compact(path, require_attributed_user=True)
        finally:
            pathlib.Path(path).unlink()

        self.assertIn("사람이 친 말", body)


class TranscriptDecodeTest(unittest.TestCase):
    """If one broken byte kills the retrospection job, that session is already marked seen and is
    never retried."""

    def test_an_undecodable_byte_does_not_kill_the_job(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as fh:
            fh.write(b'{"type":"user","message":{"role":"user","content":"before"}}\n')
            fh.write(b'{"type":"user","message":{"role":"user","content":"bad \xe9 byte"}}\n')
            fh.write(b'{"type":"user","message":{"role":"user","content":"after"}}\n')
            path = fh.name
        try:
            body, n = compact_transcript.compact(path)   # the old version raised UnicodeDecodeError here
        finally:
            pathlib.Path(path).unlink()

        self.assertGreater(n, 0)
        self.assertIn("before", body, "content before the broken line disappeared")
        self.assertIn("after", body,
                      "content after the broken line disappeared — one line cost us the rest")


class ReflectProvenanceGateTest(unittest.TestCase):
    def test_automatic_reflect_never_calls_llm_for_unattributed_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            transcript = root / "old.jsonl"
            transcript.write_text(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": "출처 불명 사용자 턴"},
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            backend = Mock(return_value="should not run")

            with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": tmp}), \
                    patch.dict(reflect.BACKENDS, {"ollama": backend}), \
                    patch.object(sys, "argv", [
                        "reflect.py", "--transcript", str(transcript), "--backend", "ollama"
                    ]):
                with self.assertRaises(SystemExit) as stopped:
                    reflect.main()

            self.assertEqual(0, stopped.exception.code)
            backend.assert_not_called()

    def test_strict_cli_rejection_is_nonzero_and_removes_stale_output(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            transcript = root / "old.jsonl"
            output = root / "compact.md"
            transcript.write_text(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": "출처 불명 사용자 턴"},
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            output.write_text("stale previous session", encoding="utf-8")

            proc = subprocess.run([
                sys.executable,
                str(ROOT / "core" / "hooks" / "compact_transcript.py"),
                str(transcript),
                "-o", str(output),
                "--require-attributed-user",
            ], capture_output=True, text=True)

            self.assertEqual(3, proc.returncode)
            self.assertIn("retrospection refused", proc.stderr)
            self.assertFalse(output.exists())

    def test_unknown_cli_option_fails_closed(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            transcript = pathlib.Path(tmp) / "session.jsonl"
            transcript.write_text(json.dumps({
                "type": "user", "promptSource": "typed",
                "message": {"role": "user", "content": "human"},
            }) + "\n", encoding="utf-8")

            proc = subprocess.run([
                sys.executable,
                str(ROOT / "core" / "hooks" / "compact_transcript.py"),
                str(transcript), "--require-attributed-users",
            ], capture_output=True, text=True)

            self.assertEqual(2, proc.returncode)
            self.assertIn("unrecognized arguments", proc.stderr)


if __name__ == "__main__":
    unittest.main()
