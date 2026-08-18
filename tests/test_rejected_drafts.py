"""폐기한 초안이 다음 세션에서 다시 생기지 않게 하는 장치 (이슈 #109).

초안을 폐기하면 `_pending/` 의 파일이 지워진다. 그러면 **거절했다는 사실이 어디에도 안
남아서**, 다음 세션이 같은 트랜스크립트를 읽고 같은 교훈을 뽑아 같은 초안을 또 만든다.

고침은 `_rejected.md` 를 회고 프롬프트에 넣는 것이다. `_decisions_index` 가 기존 ADR 을
넣어 체인 제안을 시키는 것과 같은 방식 — 유사도 판단은 LLM 이 이미 한다.
"""
import importlib.util
import pathlib
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).parents[1] / "core" / "hooks" / "reflect.py"
SPEC = importlib.util.spec_from_file_location("reflect", SCRIPT)
reflect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reflect)


class RejectedIndexTest(unittest.TestCase):
    def _project(self, body=None):
        tmp = tempfile.mkdtemp()
        memory = pathlib.Path(tmp) / ".claude" / "memory"
        memory.mkdir(parents=True)
        if body is not None:
            (memory / "_rejected.md").write_text(body, encoding="utf-8")
        return tmp

    def test_no_file_is_not_an_error(self):
        """템플릿을 안 복사한 프로젝트가 대부분이다 — 조용히 넘어가야 한다."""
        self.assertEqual("(아직 없음)", reflect._rejected_index(self._project()))

    def test_file_with_only_prose_counts_as_empty(self):
        """머리말만 있고 항목이 없는 새 파일. 설명문을 항목으로 오인하면 안 된다."""
        project = self._project("# 폐기한 초안\n\n안 남기기로 한 후보를 여기 적는다.\n")
        self.assertEqual("(아직 없음)", reflect._rejected_index(project))

    def test_entries_are_returned_for_the_prompt(self):
        project = self._project(
            "# 폐기한 초안\n\n설명 문단.\n\n"
            "- `use-tabs` — .editorconfig 가 이미 강제 (2026-08-18)\n"
            "- `short-titles` — 한 번뿐인 지적 (2026-08-18)\n"
        )
        out = reflect._rejected_index(project)
        self.assertIn("use-tabs", out)
        self.assertIn("short-titles", out)
        self.assertNotIn("설명 문단", out)

    def test_oldest_entries_drop_first_when_capped(self):
        """추가 전용이라 뒤쪽이 최신이다. 넘치면 **오래된 앞쪽**을 버린다 —
        최근에 거절한 것일수록 다시 생성될 확률이 높다."""
        rows = [f"- `lesson-{i}` — 이유 (2026-08-18)" for i in range(60)]
        project = self._project("# 폐기\n\n" + "\n".join(rows) + "\n")
        out = reflect._rejected_index(project)
        self.assertNotIn("`lesson-0`", out, "가장 오래된 항목이 남았다")
        self.assertIn("`lesson-59`", out, "가장 최근 항목이 잘렸다")
        self.assertIn("생략", out, "잘렸다는 사실을 알리지 않았다")


class CommentedExampleTest(unittest.TestCase):
    """주석 안의 예시가 **진짜 폐기 기록으로 새지 않는지.**

    파서는 `- ` 로 시작하는 줄을 항목으로 본다. 사람이 파일 안에 예시를 적을 때 자연스럽게
    `<!-- ... -->` 로 감싸는데, **줄 단위 파서는 주석을 못 본다.** 그러면 있지도 않은 거절이
    모든 회고 프롬프트에 주입돼, 비슷한 교훈이 조용히 막힌다.

    `_decisions_index` 는 이미 같은 실패를 막고 있다 — README·EXAMPLE 파일을 걸러
    "복사한 새 프로젝트에서 예시가 실제 기존 체인으로 주입되는 걸 막는다". 새 경로에 같은
    버그를 다시 넣지 않았는지 본다.
    """

    def _index(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            memory = pathlib.Path(tmp) / ".claude" / "memory"
            memory.mkdir(parents=True)
            (memory / "_rejected.md").write_text(body, encoding="utf-8")
            return reflect._rejected_index(tmp)

    def test_commented_out_examples_are_not_entries(self):
        out = self._index(
            "# 폐기한 회고 초안\n\n"
            "<!-- 예시다. 실제로는 지우고 시작한다.\n"
            "- `use-tabs-not-spaces` — .editorconfig 가 이미 강제 (2026-08-18)\n"
            "-->\n"
        )
        self.assertEqual("(아직 없음)", out,
                         f"주석 안 예시가 실제 기록으로 샜다:\n{out}")

    def test_real_entries_around_a_comment_still_count(self):
        """주석을 걷어내다 진짜 항목까지 날리면 안 된다."""
        out = self._index(
            "# 폐기\n\n"
            "- `real-one` — 실제 폐기 (2026-08-18)\n"
            "<!-- 참고: 아래는 예시\n- `fake-one` — 예시 (2026-08-18)\n-->\n"
            "- `real-two` — 실제 폐기 (2026-08-18)\n"
        )
        self.assertIn("real-one", out)
        self.assertIn("real-two", out)
        self.assertNotIn("fake-one", out)


class RenderedSkillTest(unittest.TestCase):
    """대화형 경로(`/memory-update`)에도 배선됐는지.

    자동 회고는 기본 꺼짐이라, 실제로 초안이 재생성되는 건 **대화형 경로**다 —
    `/memory-update` 가 매번 트랜스크립트에서 다시 뽑는다. reflect.py 만 고치면 정작
    아픈 쪽이 그대로다. core 를 고치고 build.sh 를 안 돌린 경우도 여기서 걸린다.
    """

    ADAPTERS = ("harness", "codex")

    def _rendered(self, adapter):
        return (pathlib.Path(__file__).parents[1] / "plugins" / adapter
                / "skills" / "memory-update" / "SKILL.md").read_text(encoding="utf-8")

    def test_both_adapters_read_and_write_the_rejection_list(self):
        for adapter in self.ADAPTERS:
            text = self._rendered(adapter)
            with self.subTest(adapter=adapter, path="읽기"):
                self.assertIn("_rejected.md", text)
                self.assertIn("후보에서 뺀다", text,
                              "dedup 단계에서 폐기 목록을 쓰라는 지시가 없다")
            with self.subTest(adapter=adapter, path="쓰기"):
                self.assertIn("append", text,
                              "폐기한 것을 기록하라는 지시가 없다 — 목록이 채워지지 않는다")

    def test_it_is_not_presented_as_a_permanent_ban(self):
        for adapter in self.ADAPTERS:
            with self.subTest(adapter=adapter):
                self.assertIn("금지 목록이 아니다", self._rendered(adapter))


class PromptWiringTest(unittest.TestCase):
    """정규화만 되고 **프롬프트에 안 실리는** 배선 누락을 잡는다.

    함수만 테스트하면 "읽기는 되는데 아무도 안 쓴다" 를 놓친다 — 이 저장소에서 두 번 그랬다.
    """

    def test_prompt_tells_the_model_to_skip_rejected_lessons(self):
        self.assertIn("이미 폐기한 초안", reflect.PROMPT,
                      "프롬프트가 폐기 목록을 언급하지 않는다 — 목록을 넣어도 모델이 안 본다")

    def test_prompt_does_not_turn_it_into_a_permanent_ban(self):
        """한 번 거절했다고 영원히 막으면 그게 또 버그다 — 반복돼 값어치가 생기면 다시 올려야 한다."""
        self.assertIn("금지 목록이 아니다", reflect.PROMPT)

    def test_rejected_index_is_assembled_into_the_prompt(self):
        source = SCRIPT.read_text(encoding="utf-8")
        assembly = source[source.index("prompt = ("):source.index("text = BACKENDS[backend]")]
        self.assertIn("_rejected_index(project_dir)", assembly,
                      "_rejected_index 가 프롬프트 조립에 안 들어갔다")


if __name__ == "__main__":
    unittest.main()
