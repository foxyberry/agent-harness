"""Pins the ADR schema to exactly one place that **ships with the plugin** (issue #132).

The `memory-update` skill used to point at `.claude/memory/decisions/README.md` as the
"canonical schema". But the plugin cache carries only `core/` and `plugins/`, never
`project-template/`. So in a project that had not copied the pack — or had copied it before
the ADR feature existed — the skill **pointed at a file that was not there**, leaving no way
to check the schema and blocking promotion.

The schema is a format the harness defines, not something that varies per project. That
makes it different from opinions such as `routes.json` or `reflection-rules.json` (what to
inject and what to warn about). It therefore belongs **where the engine ships**, not in the
opinion pack.

Two things are pinned here.

1. The schema really lands in the rendered SKILL.md of **both adapters** — `build.sh` copies
   only `SKILL.md` out of a skill folder, so a schema kept in a sibling file would silently
   not ship.
2. The schema is **not in two places** — the same fact in two places means one of them goes
   stale. A repeated failure in this repository.
"""
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_SKILL = ROOT / "core" / "skills" / "memory-update" / "SKILL.md"
RENDERED = [
    ROOT / "plugins" / "harness" / "skills" / "memory-update" / "SKILL.md",
    ROOT / "plugins" / "codex" / "skills" / "memory-update" / "SKILL.md",
]
TEMPLATE_README = (
    ROOT / "project-template" / ".claude" / "memory" / "decisions" / "README.md"
)

# The whole schema. **Do not use a hand-picked subset** — a field dropped while porting is
# also absent from the list, so the test passes. That is exactly how `artifacts` was lost,
# and a Codex review caught it. When porting, count every field of the original in.
FRONTMATTER_FIELDS = ["name:", "description:", "type: decision", "id: adr-YYYYMMDD-NNN",
                      "chain:", "status:", "supersedes:", "keywords:", "commit:", "artifacts:"]
REQUIRED_SECTIONS = ["## Context", "## Decision", "## Alternatives", "## Consequence", "## Evidence"]


class SchemaShipsWithThePluginTest(unittest.TestCase):
    def assert_adr_schema(self, path):
        text = path.read_text(encoding="utf-8")
        section = re.search(r"^### 1\.6 .*?(?=^### |\Z)", text, re.M | re.S)
        self.assertIsNotNone(section, f"no ADR promotion section: {path}")
        blocks = {}
        for language in ("yaml", "markdown"):
            block = re.search(
                rf"^```{language}\n(.*?)^```$", section.group(), re.M | re.S
            )
            self.assertIsNotNone(block, f"no ADR {language} example: {path}")
            blocks[language] = block.group(1)
        # Keep the skill's own metadata or other memory examples from masking a missing field.
        for token in FRONTMATTER_FIELDS:
            with self.subTest(path=str(path.relative_to(ROOT)), token=token):
                self.assertRegex(blocks["yaml"], r"(?m)^" + re.escape(token))
        for token in REQUIRED_SECTIONS:
            with self.subTest(path=str(path.relative_to(ROOT)), token=token):
                self.assertRegex(blocks["markdown"], r"(?m)^" + re.escape(token))

    def test_core_skill_carries_the_schema(self):
        self.assert_adr_schema(CORE_SKILL)

    def test_both_rendered_adapters_carry_the_schema(self):
        """`build.sh` copies only SKILL.md out of a skill folder — a sibling file does not ship."""
        for path in RENDERED:
            self.assert_adr_schema(path)

    def test_skill_does_not_call_the_project_file_canonical(self):
        """Calling a possibly-absent project file canonical blocks promotion in that project."""
        text = CORE_SKILL.read_text(encoding="utf-8")
        section = re.search(r"^### 1\.6 .*?(?=^### |\Z)", text, re.M | re.S)
        self.assertIsNotNone(section)
        self.assertIn("The canonical schema is defined below", section.group())
        self.assertIn("not the canonical schema", section.group())
        # Keep the negative guard across the whole skill: a correct inline schema must
        # not hide a contradictory instruction elsewhere pointing at the project file.
        # Sentence boundaries avoid flagging the explicit non-canonical disclaimer.
        # The `정본` alternative is deliberate legacy coverage: the skill text may still
        # carry the Korean word for "canonical", and dropping it would silently stop
        # guarding those sentences.
        for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
            if "decisions/README.md" in sentence and re.search(r"\bcanonical\b|정본", sentence):
                self.assertIn("not the canonical schema", sentence,
                              f"Project-local guide is presented as canonical: {sentence!r}")


class SchemaLivesInOnePlaceTest(unittest.TestCase):
    def test_template_readme_does_not_restate_the_schema(self):
        """The same schema in two places means one goes stale — a repeated failure here."""
        text = TEMPLATE_README.read_text(encoding="utf-8")
        restated = [t for t in FRONTMATTER_FIELDS if t in text]
        self.assertEqual(
            [], restated,
            "The project-template guide is restating the schema. The canonical copy is the "
            "memory-update SKILL.md alone; this file should only point at it.",
        )

    def test_template_readme_points_at_the_skill(self):
        """If it only points somewhere, it must at least say where."""
        text = TEMPLATE_README.read_text(encoding="utf-8")
        self.assertIn("memory-update", text)


if __name__ == "__main__":
    unittest.main()
