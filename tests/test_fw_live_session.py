"""fw 가 **지금 이 세션**을 "직전 작업"으로 고르지 않는지 고정한다 (이슈 #96).

`--current` 로 live 세션을 배제하는 계산은 있었는데 `--from both` 분기에서만 썼다.
그래서 같은 툴에서 세션이 끊겼을 때(재부팅·컨텍스트 소진) `--from claude` 로 찾으면
최신 = 방금 켠 세션이라 **자기 자신을 요약**했다.

배제가 못 걸리는 상황(env 부재·불일치)에서는 **아무것도 숨기지 않는다.** 잘못 숨기면
복원해야 할 직전 작업이 사라지는데, 안 숨기면 최악이라도 목록에 한 줄 더 보일 뿐이다.
이어받기는 현재 git 이 우선이라 그 편이 안전하다 — 이 fail-open 을 테스트로 고정한다.
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "core" / "scripts" / "handoff.py"
SPEC = importlib.util.spec_from_file_location("handoff_fw", SCRIPT)
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)

LIVE = "11111111-1111-1111-1111-111111111111"
PREV = "22222222-2222-2222-2222-222222222222"


def _claude_line(kind, text, ts, tool=None, tool_result=False):
    if tool:
        blocks = [{"type": "tool_use", "name": tool, "input": {"command": text}}]
        role = "assistant"
    elif tool_result:
        blocks = [{"type": "tool_result", "content": text}]
        role = "user"
    else:
        blocks = [{"type": "text", "text": text}]
        role = kind
    return json.dumps({
        "type": kind, "timestamp": ts,
        "message": {"role": role, "content": blocks},
    }, ensure_ascii=False)


class _Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self._tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        self.proj = base / "proj"
        self.proj.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.proj, check=True)
        self.root = str(self.proj.resolve())

        key = self.root.replace("/", "-").replace(".", "-")
        self.cdir = self.home / ".claude" / "projects" / key
        self.cdir.mkdir(parents=True)

        # 직전 세션 (오래됨) / live 세션 (최신) — mtime 정렬이면 live 가 이긴다.
        self._write(PREV, "직전 작업이다", 1_785_000_000)
        self._write(LIVE, "방금 켠 세션이다", 1_785_003_600)

    def _write(self, stem, text, mtime):
        path = self.cdir / f"{stem}.jsonl"
        path.write_text(_claude_line("user", text, "2026-08-12T01:00:00.000Z") + "\n",
                        encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def tearDown(self):
        self._tmp.cleanup()

    def _fw(self, *argv, session_id=LIVE):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env.pop("CODEX_THREAD_ID", None)
        env.pop("CODEX_SESSION_ID", None)
        if session_id is None:
            env.pop("CLAUDE_CODE_SESSION_ID", None)
        else:
            env["CLAUDE_CODE_SESSION_ID"] = session_id
        proc = subprocess.run(
            ["python3", str(SCRIPT), "fw", "--project-dir", self.root, *argv],
            capture_output=True, text=True, env=env, cwd=self.root,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        return proc.stdout


class LiveSessionExcludedTest(_Fixture):
    def test_from_claude_returns_previous_session_not_the_live_one(self):
        out = self._fw("--from", "claude", "--current", "claude")

        self.assertIn(PREV, out, "같은 툴 직전 세션이 나와야 한다")
        self.assertNotIn(LIVE, out, "지금 이 세션을 '직전 작업'으로 고르면 안 된다")

    def test_auto_also_excludes_the_live_session(self):
        out = self._fw("--from", "auto", "--current", "claude")

        self.assertIn(PREV, out)
        self.assertNotIn(LIVE, out)

    def test_auto_does_not_go_empty_when_the_newest_is_live(self):
        """배제 후 후보가 비면 '로그 없음'으로 떨어진다 — 멀쩡한 직전 세션을 두고도."""
        out = self._fw("--from", "auto", "--current", "claude")

        self.assertNotIn("최근 세션 로그 없음", out)

    def test_explicit_session_is_never_excluded(self):
        """`--session` 은 '이걸 보라'는 명시적 지시다. live 여도 그대로 보여준다."""
        out = self._fw("--session", str(self.cdir / f"{LIVE}.jsonl"), "--current", "claude")

        self.assertIn(LIVE, out)


class FailOpenTest(_Fixture):
    def test_nothing_is_hidden_when_env_is_absent(self):
        out = self._fw("--from", "claude", "--current", "claude", session_id=None)

        self.assertIn(LIVE, out, "배제 근거가 없으면 숨기지 않는다 — 잘못 숨기는 게 더 나쁘다")

    def test_nothing_is_hidden_when_env_matches_no_transcript(self):
        out = self._fw("--from", "claude", "--current", "claude",
                       session_id="99999999-9999-9999-9999-999999999999")

        self.assertIn(LIVE, out)

    def test_nothing_is_hidden_without_current_flag(self):
        out = self._fw("--from", "claude")

        self.assertIn(LIVE, out)


class TimelineTest(unittest.TestCase):
    def _summarize(self, lines):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            path = f.name
        try:
            return handoff._summarize_claude_transcript(path)
        finally:
            os.unlink(path)

    def test_timeline_keeps_chronological_order_across_kinds(self):
        s = self._summarize([
            _claude_line("user", "이거 고쳐줘", "2026-08-12T01:00:00.000Z"),
            _claude_line("assistant", "고치겠습니다", "2026-08-12T01:01:00.000Z"),
            _claude_line("assistant", "git status", "2026-08-12T01:02:00.000Z", tool="Bash"),
        ])

        self.assertEqual(
            ["USER", "AGENT", "TOOL"], [kind for _ts, kind, _t in s["timeline"]],
            "종류별로 나누지 말고 일어난 순서대로 이어져야 한다",
        )

    def test_tool_results_are_not_labelled_as_user_input(self):
        """Claude JSONL 은 tool_result 를 role=user 로 담는다 — 사람이 친 말이 아니다."""
        s = self._summarize([
            _claude_line("user", "빌드해줘", "2026-08-12T01:00:00.000Z"),
            _claude_line("user", "빌드 완료: 0 errors", "2026-08-12T01:01:00.000Z",
                         tool_result=True),
        ])

        kinds = [kind for _ts, kind, _t in s["timeline"]]
        texts = " ".join(t for _ts, _k, t in s["timeline"])
        self.assertEqual(["USER"], kinds)
        self.assertNotIn("0 errors", texts)
        self.assertNotIn("빌드 완료: 0 errors", s["last_users"])

    def test_mixed_tool_result_and_text_is_not_user_input(self):
        """도구 결과 뒤에 system-reminder 가 붙는 혼합 메시지 — 가장 흔한 형태다.

        "전부 tool_result 인가"로 판정하면 이 경우를 놓친다. 사람 발화만 골라 담아야 한다.
        """
        mixed = json.dumps({
            "type": "user", "timestamp": "2026-08-12T01:01:00.000Z",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "빌드 완료: 0 errors"},
                {"type": "text", "text": "<system-reminder>메모리를 참고하라</system-reminder>"},
            ]},
        }, ensure_ascii=False)

        s = self._summarize([
            _claude_line("user", "빌드해줘", "2026-08-12T01:00:00.000Z"),
            mixed,
        ])

        texts = " ".join(t for _ts, _k, t in s["timeline"])
        self.assertEqual(["USER"], [kind for _ts, kind, _t in s["timeline"]])
        self.assertNotIn("0 errors", texts)
        self.assertNotIn("system-reminder", texts)

    def test_system_reminder_only_message_is_not_user_input(self):
        s = self._summarize([
            _claude_line("user", "<system-reminder>주의</system-reminder>",
                         "2026-08-12T01:00:00.000Z"),
        ])

        self.assertEqual([], s.get("timeline", []))
        self.assertEqual([], s["last_users"])

    def test_timeline_is_capped(self):
        lines = [_claude_line("user", f"메시지 {i}", "2026-08-12T01:00:00.000Z")
                 for i in range(handoff.TIMELINE_CAP + 10)]

        s = self._summarize(lines)

        self.assertEqual(handoff.TIMELINE_CAP, len(s["timeline"]))
        self.assertIn(f"메시지 {handoff.TIMELINE_CAP + 9}", s["timeline"][-1][2])


if __name__ == "__main__":
    unittest.main()
