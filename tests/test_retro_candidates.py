"""Can the retrospection skills see **material from outside this session** (issue #81)?

Automatic retrospection (`HARNESS_AUTO_REFLECT`) is off by default, so for most users the
interactive retrospective is **the only one they get**. If that is confined to the current session:

- `/feedback-review` never sees the `_pending` drafts the retrospection job piled up
- work done in the other tool never arrives (if Codex implements and Claude only reviews, the Claude
  log holds almost no user utterances)

What is pinned here is the **wiring** -- whether the skill actually points at commands that reach
that material, and whether those commands render into a runnable form per adapter.
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
    """The problem where `/feedback-review` did not read `_pending`.

    Even with the automatic retrospective piling drafts up nicely, this skill reported zero -- not
    a fault, but by design.
    """

    def test_both_retro_skills_read_pending(self):
        for adapter in ADAPTERS:
            for skill in RETRO_SKILLS:
                with self.subTest(adapter=adapter, skill=skill):
                    self.assertIn("_pending", _rendered(adapter, skill),
                                  "the retrospection skill does not look at pending drafts")


class PastSessionTest(unittest.TestCase):
    """Can past and other-tool sessions be used as candidates, and are they **not pulled in
    automatically**?"""

    def test_skills_point_at_the_session_listing(self):
        for adapter in ADAPTERS:
            for skill in RETRO_SKILLS:
                with self.subTest(adapter=adapter, skill=skill):
                    text = _rendered(adapter, skill)
                    self.assertIn("history --from both", text,
                                  "no guidance on how to find past sessions")
                    self.assertIn("compact_transcript", text,
                                  "no way to read the chosen session's content — a listing alone "
                                  "cannot be reflected on")
                    self.assertIn("--require-attributed-user", text,
                                  "turns of unknown origin would enter as memory promotion "
                                  "candidates")

    def test_the_command_is_rendered_runnable_not_a_placeholder(self):
        """If `{{HANDOFF}}` is left as-is, copy-pasting the command does not work."""
        for adapter in ADAPTERS:
            for skill in RETRO_SKILLS:
                with self.subTest(adapter=adapter, skill=skill):
                    self.assertNotIn("{{", _rendered(adapter, skill))

    def test_codex_gets_the_project_dir_argument(self):
        """Codex does not provide CLAUDE_PROJECT_DIR -- without the argument it searches the wrong
        project."""
        for skill in RETRO_SKILLS:
            with self.subTest(skill=skill):
                text = _rendered("codex", skill)
                line = next(l for l in text.splitlines() if "history --from both" in l)
                self.assertIn("--project-dir", line)

    def test_past_sessions_are_opt_in_not_automatic(self):
        """Unbounded automatic candidates mix in feedback from unrelated work and set as **the
        wrong rule**."""
        for adapter in ADAPTERS:
            for skill in RETRO_SKILLS:
                with self.subTest(adapter=adapter, skill=skill):
                    text = _rendered(adapter, skill)
                    self.assertIn("Do not import past sessions automatically", text)
                    self.assertIn("selected by the user", text)

    def test_the_current_session_is_excluded(self):
        """Using your own session as retrospection material makes the same point circle back (the
        approach fw already uses)."""
        for adapter in ADAPTERS:
            for skill in RETRO_SKILLS:
                with self.subTest(adapter=adapter, skill=skill):
                    self.assertIn("Exclude the current session from the candidates", _rendered(adapter, skill))


class DedupTest(unittest.TestCase):
    """Pulling in the past brings back **things already dealt with** -- the question the issue left
    open."""

    def test_feedback_review_checks_the_rejection_log(self):
        """The `_rejected.md` introduced by #113 has to be used here too, or what was thrown away
        comes back."""
        for adapter in ADAPTERS:
            with self.subTest(adapter=adapter):
                self.assertIn("_rejected.md", _rendered(adapter, "feedback-review"))

    def test_it_is_not_presented_as_a_permanent_ban(self):
        for adapter in ADAPTERS:
            with self.subTest(adapter=adapter):
                self.assertIn("not a ban list", _rendered(adapter, "feedback-review"))


class BundledScriptTest(unittest.TestCase):
    """Do the commands being recommended **actually exist?** Pointing the docs at a missing tool
    blocks things silently."""

    def test_compact_transcript_ships_where_each_adapter_can_run_it(self):
        claude = ROOT / "plugins" / "harness" / "bin" / "compact_transcript.py"
        self.assertTrue(claude.is_file(), "the compactor is missing from the Claude bin/")
        self.assertTrue(claude.stat().st_mode & 0o111,
                        "not executable, so it cannot be invoked from PATH")

        for skill in RETRO_SKILLS:
            path = (ROOT / "plugins" / "codex" / "skills" / skill
                    / "scripts" / "compact_transcript.py")
            with self.subTest(skill=skill):
                self.assertTrue(path.is_file(),
                                "the compactor is missing from the Codex skill bundle")

    def test_the_bundled_compactor_actually_runs(self):
        """Being in the bundle and actually running are different -- the file exists even if its
        imports are broken."""
        script = ROOT / "plugins" / "harness" / "bin" / "compact_transcript.py"
        proc = subprocess.run([sys.executable, str(script)],
                              capture_output=True, text=True, timeout=30)
        self.assertNotEqual(2, proc.returncode,
                            f"the compactor cannot even be executed:\n{proc.stderr}")


if __name__ == "__main__":
    unittest.main()
