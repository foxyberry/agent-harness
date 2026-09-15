"""Pins that fw never picks **this very session** as "the most recent work" (issue #96).

The calculation that excludes the live session via `--current` existed, but was only used
in the `--from both` branch. So when a session broke within the same tool (reboot, context
exhaustion), searching with `--from claude` found the newest = the session just started and
**summarized itself**.

When the exclusion cannot be established (env missing or not matching), **nothing is
hidden**. Hiding wrongly makes the previous work that needed restoring disappear; not
hiding costs, at worst, one extra line in the list. Pickup is safe because current git
wins — this fail-open is what the tests below pin.

The Korean message bodies in the fixtures are deliberate: they stand in for real user
input, and neither the exclusion nor the injected-block filtering may depend on the
language of the conversation.
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import time
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

        # Previous session (older) / live session (newest) — a mtime sort lets live win.
        # Relative times only — a fixed epoch breaks itself once the recency cutoff passes.
        base = time.time() - 86400.0
        self._write(PREV, "직전 작업이다", base)
        self._write(LIVE, "방금 켠 세션이다", base + 3600)

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

        self.assertIn(PREV, out, "the previous session of the same tool has to show up")
        self.assertNotIn(LIVE, out, "this very session must not be picked as 'the most recent work'")

    def test_auto_also_excludes_the_live_session(self):
        out = self._fw("--from", "auto", "--current", "claude")

        self.assertIn(PREV, out)
        self.assertNotIn(LIVE, out)

    def test_auto_does_not_go_empty_when_the_newest_is_live(self):
        """If exclusion empties the candidate list it falls through to 'no logs' — even
        though a perfectly good previous session exists."""
        out = self._fw("--from", "auto", "--current", "claude")

        self.assertNotIn("No recent session log for this project", out)

    def test_explicit_session_is_never_excluded(self):
        """`--session` is an explicit "look at this one". It is shown even when live."""
        out = self._fw("--session", str(self.cdir / f"{LIVE}.jsonl"), "--current", "claude")

        self.assertIn(LIVE, out)


class FailOpenTest(_Fixture):
    def test_nothing_is_hidden_when_env_is_absent(self):
        out = self._fw("--from", "claude", "--current", "claude", session_id=None)

        self.assertIn(LIVE, out,
                      "with no grounds for exclusion, hide nothing — hiding wrongly is worse")

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
            "entries must follow the order they happened in, not be split by kind",
        )

    def test_tool_results_are_not_labelled_as_user_input(self):
        """Claude JSONL carries tool_result under role=user — that is not human speech."""
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
        """A mixed message with a system-reminder after the tool result — the most common
        shape.

        Deciding by "is everything a tool_result?" misses this case. Only human speech may
        be collected.
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
