"""회고 잡이 LLM 출력과 트랜스크립트를 읽다 **조용히 잃는** 경우 (리뷰 지적).

둘 다 실패가 "초안 없음" 으로 보인다 — 뽑을 게 없었던 것과 구별이 안 된다.
"""
import importlib.util
import pathlib
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()
