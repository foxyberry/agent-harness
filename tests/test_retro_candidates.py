"""회고 스킬이 **이번 세션 밖의 재료**를 볼 수 있는지 (이슈 #81).

자동 회고(`HARNESS_AUTO_REFLECT`)는 기본 꺼짐이라, 대부분의 사용자에게 대화형 회고가
**유일한 회고 수단**이다. 그런데 그게 현재 세션에만 갇혀 있으면:

- 회고 잡이 쌓아둔 `_pending` 초안을 `/feedback-review` 가 아예 못 본다
- 반대 툴에서 한 작업이 안 들어온다 (Codex 가 구현하고 Claude 가 리뷰만 하면
  Claude 로그에 사용자 발화가 거의 없다)

여기서 지키는 것은 **배선**이다 — 스킬이 실제로 그 재료에 닿는 명령을 안내하는지,
그리고 그 명령이 어댑터별로 실행 가능한 형태로 렌더되는지.
"""
import pathlib
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
ADAPTERS = ("harness", "codex")
RETRO_SKILLS = ("feedback-review", "memory-update")


def _rendered(adapter, skill):
    return (ROOT / "plugins" / adapter / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")


class PendingDraftsTest(unittest.TestCase):
    """`/feedback-review` 가 `_pending` 을 안 읽던 문제.

    자동 회고가 초안을 잘 쌓아뒀어도 이 스킬은 0건을 냈다 — 고장이 아니라 설계상 그랬다.
    """

    def test_both_retro_skills_read_pending(self):
        for adapter in ADAPTERS:
            for skill in RETRO_SKILLS:
                with self.subTest(adapter=adapter, skill=skill):
                    self.assertIn("_pending", _rendered(adapter, skill),
                                  "회고 스킬이 대기 초안을 안 본다")


class PastSessionTest(unittest.TestCase):
    """과거·반대 툴 세션을 후보로 쓸 수 있는지, 그리고 **자동으로 끌어오지 않는지**."""

    def test_skills_point_at_the_session_listing(self):
        for adapter in ADAPTERS:
            for skill in RETRO_SKILLS:
                with self.subTest(adapter=adapter, skill=skill):
                    text = _rendered(adapter, skill)
                    self.assertIn("history --from both", text,
                                  "과거 세션을 찾는 방법을 안내하지 않는다")
                    self.assertIn("compact_transcript", text,
                                  "고른 세션의 내용을 읽는 방법이 없다 — 목록만으로는 회고 못 한다")
                    self.assertIn("--require-attributed-user", text,
                                  "출처 불명 턴도 메모리 승격 후보로 들어간다")

    def test_the_command_is_rendered_runnable_not_a_placeholder(self):
        """`{{HANDOFF}}` 가 그대로 남으면 복붙해도 안 돈다."""
        for adapter in ADAPTERS:
            for skill in RETRO_SKILLS:
                with self.subTest(adapter=adapter, skill=skill):
                    self.assertNotIn("{{", _rendered(adapter, skill))

    def test_codex_gets_the_project_dir_argument(self):
        """Codex 는 CLAUDE_PROJECT_DIR 을 안 준다 — 인자가 없으면 엉뚱한 프로젝트를 뒤진다."""
        for skill in RETRO_SKILLS:
            with self.subTest(skill=skill):
                text = _rendered("codex", skill)
                line = next(l for l in text.splitlines() if "history --from both" in l)
                self.assertIn("--project-dir", line)

    def test_past_sessions_are_opt_in_not_automatic(self):
        """무제한 자동 후보는 무관한 작업의 피드백을 섞어 **잘못된 규칙**으로 굳는다."""
        for adapter in ADAPTERS:
            for skill in RETRO_SKILLS:
                with self.subTest(adapter=adapter, skill=skill):
                    text = _rendered(adapter, skill)
                    self.assertIn("자동으로 끌어오지 않는다", text)
                    self.assertIn("사용자가 고른", text)

    def test_the_current_session_is_excluded(self):
        """자기 세션을 회고 재료로 쓰면 같은 얘기가 맴돈다 (fw 가 이미 쓰는 방식)."""
        for adapter in ADAPTERS:
            for skill in RETRO_SKILLS:
                with self.subTest(adapter=adapter, skill=skill):
                    self.assertIn("지금 이 세션은 후보에서 뺀다", _rendered(adapter, skill))


class DedupTest(unittest.TestCase):
    """과거를 끌어오면 **이미 처리한 것**이 다시 올라온다 — 이슈가 미해결로 남긴 질문."""

    def test_feedback_review_checks_the_rejection_log(self):
        """#113 이 만든 `_rejected.md` 가 여기서도 쓰여야 한다. 안 그러면 버린 게 또 온다."""
        for adapter in ADAPTERS:
            with self.subTest(adapter=adapter):
                self.assertIn("_rejected.md", _rendered(adapter, "feedback-review"))

    def test_it_is_not_presented_as_a_permanent_ban(self):
        for adapter in ADAPTERS:
            with self.subTest(adapter=adapter):
                self.assertIn("금지 목록이 아니다", _rendered(adapter, "feedback-review"))


class BundledScriptTest(unittest.TestCase):
    """안내한 명령이 **실제로 존재하는지.** 문서가 없는 도구를 가리키면 조용히 막힌다."""

    def test_compact_transcript_ships_where_each_adapter_can_run_it(self):
        claude = ROOT / "plugins" / "harness" / "bin" / "compact_transcript.py"
        self.assertTrue(claude.is_file(), "Claude bin/ 에 압축기가 없다")
        self.assertTrue(claude.stat().st_mode & 0o111,
                        "실행 권한이 없어 PATH 에서 못 부른다")

        for skill in RETRO_SKILLS:
            path = (ROOT / "plugins" / "codex" / "skills" / skill
                    / "scripts" / "compact_transcript.py")
            with self.subTest(skill=skill):
                self.assertTrue(path.is_file(), "Codex 스킬 번들에 압축기가 없다")

    def test_the_bundled_compactor_actually_runs(self):
        """번들에 있는 것과 도는 것은 다르다 — import 가 깨져도 파일은 존재한다."""
        script = ROOT / "plugins" / "harness" / "bin" / "compact_transcript.py"
        proc = subprocess.run([sys.executable, str(script)],
                              capture_output=True, text=True, timeout=30)
        self.assertNotEqual(2, proc.returncode,
                            f"압축기를 실행조차 못 한다:\n{proc.stderr}")


if __name__ == "__main__":
    unittest.main()
