"""Pins that session-log discovery is scoped to the **current project** (issue #95).

What happened: a pickup in project A reported a session from project B — globally newer by
mtime — as "the most recent work". The cause was not a missing scoped selector but
**never reaching** it:
  - `load --deep` never called the Codex summary at all, and
  - the hint scanned all of `~/.codex/sessions` and only said "they exist".
So people and models dug through the logs by hand, and hand-digging has no scoping.

Two things are pinned here: "pick only my project's logs even when several projects'
logs are mixed together", and "say so plainly when nothing is found".
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
SPEC = importlib.util.spec_from_file_location("handoff", SCRIPT)
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)


def _git_init(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return str(path.resolve())


def _write_rollout(home, name, sid, cwd, mtime):
    """Create one ~/.codex/sessions/<date tree>/rollout-*.jsonl.

    The message body stays Korean on purpose: these fixtures stand in for real user input,
    and scoping must not depend on the language of the conversation.
    """
    p = pathlib.Path(home, ".codex", "sessions", "2026", "08", "11", name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": sid, "cwd": cwd}}) + "\n"
        + json.dumps({"type": "message", "role": "user", "content": "직전 작업 내용"}) + "\n",
        encoding="utf-8",
    )
    os.utime(p, (mtime, mtime))
    return p


def _write_claude_transcript(home, project_dir, stem, mtime):
    key = project_dir.replace("/", "-").replace(".", "-")
    p = pathlib.Path(home, ".claude", "projects", key, f"{stem}.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "직전 작업"}}) + "\n",
        encoding="utf-8",
    )
    os.utime(p, (mtime, mtime))
    return p


class _TwoProjects(unittest.TestCase):
    """Project A (mine) and B (someone else's). B's log is always the newer one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self._tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        self.a = _git_init(base / "proj-a")
        self.b = _git_init(base / "proj-b")
        # Make B newer — a global mtime sort would let B win.
        # A fixed epoch must not be used: rollout discovery only reads files whose mtime is
        # within 30 days, so a hard-coded value breaks CI the moment that date passes,
        # without any code change (this actually happened).
        self.now = time.time() - 86400.0
        self._env = dict(os.environ)
        os.environ["HOME"] = str(self.home)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()


class CodexRolloutScopeTest(_TwoProjects):
    def test_newer_other_project_rollout_is_not_returned(self):
        _write_rollout(self.home, "rollout-a.jsonl", "sid-a", self.a, self.now - 3600)
        _write_rollout(self.home, "rollout-b.jsonl", "sid-b", self.b, self.now)

        rows = handoff._recent_codex_rollouts(self.a, limit=10)

        self.assertEqual(
            ["rollout-a.jsonl"], [os.path.basename(r[2]) for r in rows],
            "another project's rollout must not slip in just by being globally newer",
        )

    def test_subdirectory_cwd_still_belongs_to_project(self):
        sub = pathlib.Path(self.a, "src", "deep")
        sub.mkdir(parents=True)
        _write_rollout(self.home, "rollout-sub.jsonl", "sid-sub", str(sub), self.now)

        rows = handoff._recent_codex_rollouts(self.a, limit=10)

        self.assertEqual(["rollout-sub.jsonl"], [os.path.basename(r[2]) for r in rows])


class TranscriptHintTest(_TwoProjects):
    def test_no_codex_hint_when_only_other_project_has_rollouts(self):
        _write_rollout(self.home, "rollout-b.jsonl", "sid-b", self.b, self.now)

        hints = handoff.transcript_hint(self.a)

        self.assertEqual(
            [], [h for h in hints if "Codex" in h],
            "an 'exists' hint when only another project has rollouts invites hand-digging",
        )

    def test_codex_hint_present_for_own_rollout(self):
        _write_rollout(self.home, "rollout-a.jsonl", "sid-a", self.a, self.now)

        hints = handoff.transcript_hint(self.a)

        self.assertTrue([h for h in hints if "Codex rollout present" in h])

    def test_hint_stops_reading_once_a_match_is_found(self):
        """The hint runs on every ordinary `load`. It must not force a full scan.

        When my project's session is the newest, it should read that one and stop — no
        matter how many other-project rollouts sit behind it.
        """
        # A has to be the newest — the "opened only one" assertion below relies on that order.
        _write_rollout(self.home, "rollout-a.jsonl", "sid-a", self.a, self.now)
        for i in range(20):
            _write_rollout(self.home, f"rollout-b{i}.jsonl", f"sid-b{i}", self.b, self.now - 100 - i)

        opened = []
        real = handoff._codex_rollout_meta

        def counting_meta(path):
            opened.append(path)
            return real(path)

        handoff._codex_rollout_meta = counting_meta
        try:
            self.assertTrue(handoff._has_project_codex_rollout(self.a))
        finally:
            handoff._codex_rollout_meta = real

        self.assertEqual(
            1, len(opened),
            f"should stop at the newest match, but opened {len(opened)} files",
        )

    def test_hint_names_only_commands_that_exist(self):
        _write_claude_transcript(self.home, self.a, "sess-a", self.now)
        _write_rollout(self.home, "rollout-a.jsonl", "sid-a", self.a, self.now)

        joined = "\n".join(handoff.transcript_hint(self.a))

        # Naming a command that does not exist means the user types it, nothing happens,
        # and they end up searching by hand.
        for dead in ("/fw-claude", "/continue-claude"):
            self.assertNotIn(dead, joined)
        self.assertIn("/fw-both", joined)


class LoadDeepTest(_TwoProjects):
    def _run_load_deep(self, project_dir):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        proc = subprocess.run(
            ["python3", str(SCRIPT), "load", "--deep", "--project-dir", project_dir],
            capture_output=True, text=True, env=env, cwd=project_dir,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        return proc.stdout

    def test_deep_summarizes_this_projects_codex_session(self):
        _write_rollout(self.home, "rollout-a.jsonl", "sid-a", self.a, self.now - 3600)
        _write_rollout(self.home, "rollout-b.jsonl", "sid-b", self.b, self.now)

        out = self._run_load_deep(self.a)

        # The Codex summary itself has to appear — it used to summarize Claude and stop here.
        self.assertIn("Codex rollout", out)
        self.assertIn("rollout-a.jsonl", out)
        self.assertNotIn("rollout-b.jsonl", out)

    def test_deep_says_none_instead_of_pointing_at_other_projects(self):
        _write_rollout(self.home, "rollout-b.jsonl", "sid-b", self.b, self.now)

        out = self._run_load_deep(self.a)

        self.assertIn("no recent session log for this project", out)
        self.assertNotIn("rollout-b.jsonl", out)


class TargetDisclosureTest(_TwoProjects):
    """The output has to reveal which project was inspected.

    Pointing at the wrong target is not itself a defect of the tool — it did what it was
    told. The defect is **having no way to notice it was wrong**. The output used to carry
    only a branch name, so aiming at the wrong repository still produced that repository's
    branch and sessions, looking perfectly normal.
    """

    def _run(self, *argv):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env.pop("CLAUDE_PROJECT_DIR", None)
        proc = subprocess.run(
            ["python3", str(SCRIPT), *argv],
            capture_output=True, text=True, env=env, cwd=self.a,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        return proc.stdout

    def test_load_shows_resolved_root_and_why(self):
        out = self._run("load", "--project-dir", self.b)

        self.assertIn(self.b, out,
                      "without the chosen project root in the output, a mis-aim goes unnoticed")
        self.assertIn("--project-dir", out, "the reason for that root has to be stated too")

    def test_fw_shows_resolved_root(self):
        out = self._run("fw", "--from", "claude", "--project-dir", self.b)

        self.assertIn(self.b, out)

    def test_root_source_says_cwd_when_not_given(self):
        out = self._run("load")

        self.assertIn(self.a, out)
        self.assertIn("current directory", out)

    def test_history_names_project_even_with_no_results(self):
        # With no results, "did I pick the wrong target" and "is there really nothing" must
        # stay distinguishable.
        out = self._run("history", "--project-dir", self.b)

        self.assertIn(self.b, out)


if __name__ == "__main__":
    unittest.main()
