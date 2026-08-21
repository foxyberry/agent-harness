"""회고 잡이 LLM 출력과 트랜스크립트를 읽다 **조용히 잃는** 경우 (리뷰 지적).

둘 다 실패가 "초안 없음" 으로 보인다 — 뽑을 게 없었던 것과 구별이 안 된다.
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
description: 한 줄
type: feedback
---
본문."""


class NestedFenceTest(unittest.TestCase):
    """초안 안의 코드 인용이 초안을 자르지 않는지.

    ADR 계약이 `Evidence` 섹션을 요구하므로 코드 인용은 예외가 아니라 기본이다. 바깥 펜스와
    안쪽 인용이 둘 다 ``` 이면 **구별할 방법이 없다** — 태그 없는 인용은 닫는 펜스와 글자까지
    같다. 그래서 프롬프트가 바깥에 백틱 4개를 요구하고, 파서가 그걸 읽는다.
    """

    def test_a_draft_quoting_untagged_code_survives_intact(self):
        """태그 없는 ``` 인용 — 예전 파서가 여기서 잘렸다."""
        text = f"````\n{DRAFT}\n\n## Evidence\n```\nprint(1)\n```\n끝 문장.\n````\n"

        drafts = reflect._split_drafts(text)

        self.assertEqual(1, len(drafts), f"블록이 쪼개졌다: {drafts}")
        self.assertIn("끝 문장", drafts[0], "안쪽 펜스에서 잘렸다")
        self.assertIn("print(1)", drafts[0], "인용한 코드가 사라졌다")

    def test_a_draft_quoting_tagged_code_survives_intact(self):
        text = f"````\n{DRAFT}\n\n```python\nprint(1)\n```\n끝 문장.\n````\n"

        drafts = reflect._split_drafts(text)

        self.assertEqual(1, len(drafts))
        self.assertIn("끝 문장", drafts[0])

    def test_two_separate_drafts_are_still_two(self):
        """모호함을 없애다 반대로 다 이어 붙이면 안 된다."""
        text = (f"````\n{DRAFT}\n````\n\n사이 설명\n\n"
                f"````\n{DRAFT.replace('one', 'two')}\n````\n")

        drafts = reflect._split_drafts(text)

        self.assertEqual(2, len(drafts))
        self.assertNotIn("사이 설명", drafts[0])

    def test_a_truncated_final_block_is_kept_not_dropped(self):
        """출력이 토큰 상한에 잘리면 닫는 펜스가 없다. 버리면 '뽑을 게 없었다' 와 구별이 안 된다."""
        text = f"````\n{DRAFT}\n\n마지막 줄이 잘림"

        drafts = reflect._split_drafts(text)

        self.assertEqual(1, len(drafts), "잘린 초안을 통째로 버렸다")
        self.assertIn("lesson-one", drafts[0])

    def test_old_three_tick_output_still_parses(self):
        """모델이 지시를 벗어나 백틱 3개로 낼 수 있다. 그 경우도 초안을 잃지 않는다."""
        text = f"```\n{DRAFT}\n```\n"

        self.assertEqual(1, len(reflect._split_drafts(text)))

    def test_known_limit_three_tick_outer_with_nested_quote_is_ambiguous(self):
        """**의도된 한계를 못으로 박아둔다.**

        바깥이 3개면 안쪽 태그 없는 인용과 닫는 펜스가 같은 문자열이라 원리적으로 구별이
        안 된다. 파서를 더 영리하게 만드는 게 아니라 **계약(백틱 4개)으로** 푼 이유다.
        이 테스트가 깨진다면 누가 폴백 경로를 추측으로 고치려 한 것이니, 그때 다시 판단한다.
        """
        text = f"```\n{DRAFT}\n\n```\nprint(1)\n```\n끝 문장.\n```\n"

        drafts = reflect._split_drafts(text)

        self.assertEqual(1, len(drafts))
        self.assertNotIn("끝 문장", drafts[0], "폴백 경로가 갑자기 정확해졌다 — 확인 필요")

    def test_garbage_without_the_required_markers_is_still_dropped(self):
        """살리는 것과 아무거나 받는 건 다르다."""
        self.assertEqual([], reflect._split_drafts("````\n그냥 산문\n````\n"))
        self.assertEqual([], reflect._split_drafts("````\n닫히지 않은 산문"))


class CodexUserMessageTest(unittest.TestCase):
    """Codex 롤아웃에서 **주입된 컨텍스트**를 사용자 발화로 읽지 않는지.

    Codex 는 자기가 주입한 것도 `response_item` 에 `role: "user"` 로 넣는다 —
    `<user_action>` 래퍼, 환경 정보, 프로젝트의 AGENTS.md 본문. 실측(8개 세션)에서
    그런 항목 17건 중 8건이 주입이었다.

    회고 재료로 쓰면 치명적이다. AGENTS.md 전문이 "사용자가 한 말" 로 들어가면 회고가 그걸
    새 교훈으로 뽑아 승격 후보로 올린다 — **기존 규칙이 사용자 피드백으로 둔갑해 자기복제한다.**
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
        self.assertNotIn("주입된 지시", out, "주입된 컨텍스트가 사용자 발화로 들어왔다")

    def test_developer_instructions_are_not_feedback_either(self):
        out = self._compact([self.DEVELOPER, self.REAL])

        self.assertNotIn("시스템 지시문", out)

    def test_assistant_text_still_survives(self):
        """주입을 걸러내다 응답까지 날리면 회고가 결론을 못 본다."""
        out = self._compact([self.REAL, self.ASSISTANT])

        self.assertIn("진짜 사용자 발화다", out)
        self.assertIn("어시스턴트 답변", out)

    def test_claude_real_turns_survive(self):
        """주 사용처다. 거르다 진짜 발화를 죽이면 회고 자체가 죽는다."""
        out = self._compact([
            {"type": "user", "message": {"role": "user", "content": "클로드 발화"}},
            {"type": "assistant", "message": {"role": "assistant",
                                              "content": [{"type": "text", "text": "클로드 답변"}]}},
        ])

        self.assertIn("클로드 발화", out)
        self.assertIn("클로드 답변", out)


class ClaudeInjectedTurnTest(unittest.TestCase):
    """Claude 쪽도 `role: "user"` 자리에 주입이 온다 — Codex 와 같은 부류.

    이전 판의 테스트는 "Claude 사용자 텍스트가 **필터 없이** 살아남는다" 를 지켰다. 즉
    결함 동작을 올바름으로 못박고 있었다. 실측: 한 트랜스크립트에서 USER 블록 9개 중 6개가
    주입이었고, 그중엔 **스킬 본문**이 있었다 — 하네스 자신의 규칙이 사용자 발화로 둔갑한다.
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
        """최근 트랜스크립트는 origin 을 달고 온다. 있으면 그걸 믿는다."""
        out = self._compact([
            self._user("사람이 친 말", **self.HUMAN),
            self._user("도구가 넣은 것", origin={"kind": "task-notification"}),
        ])

        self.assertIn("사람이 친 말", out)
        self.assertNotIn("도구가 넣은 것", out)

    def test_prompt_source_is_read_from_the_record_not_from_origin(self):
        """`promptSource` 는 레코드 최상위에 있다. origin 안에서 읽으면 죽은 조건이다
        (실측: `origin.promptSource` 는 2616건 전부 None)."""
        out = self._compact([
            self._user("사람이 친 말", promptSource="typed"),
            self._user("자동화가 넣은 평문 프롬프트", promptSource="sdk"),
            self._user("시스템이 넣은 평문", promptSource="system"),
        ])

        self.assertIn("사람이 친 말", out)
        self.assertNotIn("자동화가 넣은 평문 프롬프트", out,
                         "SDK 프롬프트가 사용자 피드백으로 들어왔다")
        self.assertNotIn("시스템이 넣은 평문", out)

    def test_machine_prompts_without_a_tag_are_still_caught(self):
        """마커 폴백으로는 못 잡는 부류다 — 평문이라 태그가 없다.
        origin 도 없어서(실측 sdk 40건이 그렇다) promptSource 만이 유일한 신호다."""
        out = self._compact([self._user("이 PR 을 리뷰해주세요", promptSource="sdk")])

        self.assertNotIn("리뷰해주세요", out)

    def test_meta_records_are_dropped(self):
        self.assertNotIn("메타", self._compact([self._user("메타 레코드", isMeta=True)]))

    def test_old_records_without_origin_fall_back_to_markers(self):
        """origin 이 생기기 전 파일이 훨씬 많다(이 프로젝트 46개 중 40개).
        엄격히 걸면 그 파일들에서 사용자 발화가 0건이 되고, '회고할 게 없었다' 와 구별이 안 된다."""
        out = self._compact([
            self._user("옛 파일의 진짜 발화"),
            self._user("<task-notification>\n작업 알림 본문"),
            self._user("Base directory for this skill: /x/skills/feedback-review\n스킬 규칙 본문"),
            self._user("<local-command-caveat>Caveat: ...</local-command-caveat>"),
        ])

        self.assertIn("옛 파일의 진짜 발화", out)
        self.assertNotIn("작업 알림 본문", out)
        self.assertNotIn("스킬 규칙 본문", out, "스킬 본문이 사용자 발화로 들어왔다")
        self.assertNotIn("Caveat", out)

    def test_whole_injected_families_are_filtered_not_just_the_tags_i_thought_of(self):
        """태그를 하나씩 적으면 반드시 빠뜨린다.

        첫 판은 `<command-name>` 만 적고 `<command-message>` 를 빠뜨렸다 — 실측 corpus 에
        6건 있었다. 같은 계열은 변형이 계속 생기므로 **계열 접두사**로 잡는다.
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
                self.assertNotIn(f"주입된 본문 {i}", out)

    def test_talking_about_a_marker_is_not_injection(self):
        """마커를 **언급하는** 정상 발화까지 죽이면 안 된다 — 그래서 머리에서만 본다."""
        out = self._compact([
            self._user("압축기가 <task-notification> 을 왜 거르는지 설명해줘"),
        ])

        self.assertIn("왜 거르는지", out)

    def test_the_fallback_announces_itself(self):
        """폴백은 origin 기반보다 약하다. 조용히 퇴화하면 이 저장소의 그 실패 모드다."""
        import contextlib, io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self._compact([self._user("origin 없는 발화")])

        self.assertIn("마커 기반", err.getvalue())

    def test_no_fallback_notice_when_origin_is_present(self):
        """신호가 있으면 경고가 뜨면 안 된다 — 매번 뜨면 아무도 안 읽는다."""
        import contextlib, io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self._compact([self._user("사람이 친 말", **self.HUMAN)])

        self.assertNotIn("마커 기반", err.getvalue())

    def test_retrospective_mode_refuses_unattributed_user_turns(self):
        """복원은 fallback 을 써도 되지만, 메모리 후보는 출처 불명 턴에서 만들지 않는다."""
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
        """실제 파일은 사람 턴과 command 주입이 섞인다. 파일 단위로 거부하면 안 된다."""
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
    """깨진 바이트 하나로 회고 잡이 죽으면, 그 세션은 이미 seen 처리돼 영영 재시도 안 된다."""

    def test_an_undecodable_byte_does_not_kill_the_job(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as fh:
            fh.write(b'{"type":"user","message":{"role":"user","content":"before"}}\n')
            fh.write(b'{"type":"user","message":{"role":"user","content":"bad \xe9 byte"}}\n')
            fh.write(b'{"type":"user","message":{"role":"user","content":"after"}}\n')
            path = fh.name
        try:
            body, n = compact_transcript.compact(path)   # 예전 판은 여기서 UnicodeDecodeError
        finally:
            pathlib.Path(path).unlink()

        self.assertGreater(n, 0)
        self.assertIn("before", body, "깨진 줄 앞이 사라졌다")
        self.assertIn("after", body, "깨진 줄 뒤가 사라졌다 — 한 줄 때문에 나머지를 잃었다")


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
            self.assertIn("회고 거부", proc.stderr)
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
