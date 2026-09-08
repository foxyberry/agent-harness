"""ADR 스키마가 **플러그인과 함께 배포되는 곳**에 하나만 있는지 고정한다 (이슈 #132).

`memory-update` 스킬이 `.claude/memory/decisions/README.md` 를 "스키마 정본"이라고 가리키고
있었다. 그런데 플러그인 캐시에는 `core/`·`plugins/` 만 실리고 `project-template/` 은 안 실린다.
그래서 팩을 복사하지 않았거나 ADR 기능이 생기기 전에 복사한 프로젝트에서는 **정본이 없는 파일을
가리켰고**, 사람이 스키마를 확인할 방법이 없어 승격이 막혔다.

스키마는 프로젝트마다 다른 게 아니라 하네스가 정하는 형식이다. `routes.json` 이나
`reflection-rules.json` 같은 의견(무엇을 주입·경고할지)과 다르다. 그러니 의견 팩이 아니라
**엔진과 같이 배포되는 곳**에 있어야 한다.

여기서 고정하는 것은 두 가지다.

1. 스키마가 렌더된 SKILL.md **양쪽 어댑터**에 실제로 들어간다 — `build.sh` 는 스킬 폴더에서
   `SKILL.md` 만 복사하므로, 스키마를 옆에 파일로 두면 조용히 안 실린다.
2. 스키마가 **두 곳에 있지 않다** — 같은 사실이 두 곳이면 하나가 낡는다. 이 저장소에서
   반복된 실패다.
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

# 스키마를 이루는 것 — 이게 없으면 사람이 ADR 을 만들 수 없다.
FRONTMATTER_FIELDS = ["id: adr-YYYYMMDD-NNN", "chain:", "status:", "supersedes:", "keywords:"]
REQUIRED_SECTIONS = ["## Context", "## Decision", "## Alternatives", "## Consequence", "## Evidence"]


class SchemaShipsWithThePluginTest(unittest.TestCase):
    def test_core_skill_carries_the_schema(self):
        text = CORE_SKILL.read_text(encoding="utf-8")
        for token in FRONTMATTER_FIELDS + REQUIRED_SECTIONS:
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_both_rendered_adapters_carry_the_schema(self):
        """`build.sh` 는 스킬 폴더에서 SKILL.md 만 복사한다 — 옆에 둔 파일은 안 실린다."""
        for path in RENDERED:
            text = path.read_text(encoding="utf-8")
            for token in FRONTMATTER_FIELDS + REQUIRED_SECTIONS:
                with self.subTest(adapter=path.parts[-4], token=token):
                    self.assertIn(token, text)

    def test_skill_does_not_call_the_project_file_canonical(self):
        """프로젝트에 없을 수 있는 파일을 정본이라 부르면 그 프로젝트는 승격이 막힌다."""
        text = CORE_SKILL.read_text(encoding="utf-8")
        for m in re.finditer(r"정본[^\n]*", text):
            line = m.group(0)
            if "decisions/README.md" in line:
                self.fail(f"스킬이 프로젝트 파일을 스키마 정본으로 가리킨다: {line!r}")


class SchemaLivesInOnePlaceTest(unittest.TestCase):
    def test_template_readme_does_not_restate_the_schema(self):
        """같은 스키마가 두 곳이면 하나가 낡는다 — 이 저장소에서 반복된 실패다."""
        text = TEMPLATE_README.read_text(encoding="utf-8")
        restated = [t for t in FRONTMATTER_FIELDS if t in text]
        self.assertEqual(
            [], restated,
            "project-template 의 안내 문서가 스키마를 다시 적고 있다. 정본은 "
            "memory-update SKILL.md 하나이고, 여기서는 그쪽을 가리키기만 한다.",
        )

    def test_template_readme_points_at_the_skill(self):
        """가리키기만 할 거면 어디를 가리키는지는 있어야 한다."""
        text = TEMPLATE_README.read_text(encoding="utf-8")
        self.assertIn("memory-update", text)


if __name__ == "__main__":
    unittest.main()
