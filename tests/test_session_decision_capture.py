"""Pins the session-level decision capture path (issue #153).

The ADR schema shipped in #137, but nothing ever reached it: `reflect.py` is gated behind an
opt-in, `mine.py` is a manual CLI, and the interactive retrospective extracted only
`feedback`, `project` and `reference` candidates. So a session that made a decision produced
no ADR candidate, and three weeks after the schema shipped this repository still had zero
promoted decisions.

Three things are pinned here, in the rendered skills of **both adapters** as well as core —
`build.sh` renders per adapter, so a rule that exists only in `core/` does not ship.

1. `memory-update` extracts `decision` candidates from the session, not only from draft files.
2. That extraction carries the **no-invented-alternatives** rule. `mine.py` produced a draft
   whose `## Alternatives` appeared in no source, because the 1.6 gate requires the section
   and the model filled it. A promoted ADR asserting a decision history that never happened is
   worse than no ADR, and `supersedes` chains would build on it.
3. `feedback-review` routes a decision to `memory-update` instead of storing it as a rule. A
   rule has no chain and no id, so it cannot be superseded later.
"""
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]

MEMORY_UPDATE = [
    ROOT / "core" / "skills" / "memory-update" / "SKILL.md",
    ROOT / "plugins" / "harness" / "skills" / "memory-update" / "SKILL.md",
    ROOT / "plugins" / "codex" / "skills" / "memory-update" / "SKILL.md",
]
FEEDBACK_REVIEW = [
    ROOT / "core" / "skills" / "feedback-review" / "SKILL.md",
    ROOT / "plugins" / "harness" / "skills" / "feedback-review" / "SKILL.md",
    ROOT / "plugins" / "codex" / "skills" / "feedback-review" / "SKILL.md",
]


def _extraction_section(text):
    """The candidate-extraction step (section 2), where the categories are listed.

    Scoped deliberately: `decision` appears all over 1.6, so searching the whole file would
    pass even with the category missing — which is the state this test exists to catch.
    """
    start = text.index("### 2. Extract candidates")
    end = text.index("### 2.4 ", start)
    return text[start:end]


class SessionDecisionCaptureTest(unittest.TestCase):
    def test_extraction_step_lists_a_decision_category(self):
        for path in MEMORY_UPDATE:
            with self.subTest(skill=path.relative_to(ROOT).as_posix()):
                section = _extraction_section(path.read_text(encoding="utf-8"))
                self.assertIn("**decision", section)
                # It has to send them to 1.6; a category that lands in ordinary memory gets no
                # chain, no id and no INDEX entry.
                self.assertIn("1.6", section)

    def test_extraction_step_forbids_inventing_alternatives(self):
        for path in MEMORY_UPDATE:
            with self.subTest(skill=path.relative_to(ROOT).as_posix()):
                section = _extraction_section(path.read_text(encoding="utf-8"))
                self.assertIn("Never fill the section to pass the gate", section)
                self.assertIn("Evidence", section)

    def test_promotion_step_accepts_session_candidates(self):
        for path in MEMORY_UPDATE:
            with self.subTest(skill=path.relative_to(ROOT).as_posix()):
                text = path.read_text(encoding="utf-8")
                start = text.index("### 1.6 ")
                end = text.index("### 2. Extract candidates", start)
                self.assertIn("Session candidates", text[start:end])

    def test_feedback_review_routes_decisions_to_memory_update(self):
        for path in FEEDBACK_REVIEW:
            with self.subTest(skill=path.relative_to(ROOT).as_posix()):
                text = path.read_text(encoding="utf-8")
                # The routing sentence itself, not the words: "decision" and "memory-update"
                # both appear in the unchanged skill, so loose substrings pass either way.
                self.assertIn("is not feedback", text)
                self.assertIn("section 1.6 promotes it as an ADR", text)


if __name__ == "__main__":
    unittest.main()
