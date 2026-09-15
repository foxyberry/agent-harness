"""Checks that rendered SKILL.md files never advertise a **command that does not exist**.

Advertising a missing command means the user types it and nothing happens, and the model
cannot follow the instruction either, so it ends up digging through logs by hand.
Hand-digging has no project scoping (issue #95).

This check exists because the same mistake happened **twice**: `/fw-claude` and
`/continue-claude` appeared **both** in the hint text of `handoff.py` and in the
`DEEP_RECOVERY` render value of `build.sh`, and only one side was fixed. When the same fact
lives in several places, human eyes are guaranteed to miss one.

Then it happened twice more.

- PR #105: five skills were removed from the repository but `docs/overview.html` was
  missed. README links it as the "illustrated design overview", so anyone following that
  link reads **usage instructions for commands that do not exist**. The cause was that the
  grep used to sweep the references excluded `.html` via `--include`.
- The same PR: **the regression guard in this very file** also filtered extensions down to
  `{md, py, sh, json}` and therefore never looked at `.html`. The guard built to prevent
  this mistake had the same blind spot.

So it now **does not filter by extension.** Every file that reads as text is inspected.
"""
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "core" / "skills"
RENDERED = [ROOT / "plugins" / "harness" / "skills", ROOT / "plugins" / "codex" / "skills"]

# Only backtick-wrapped slash commands are inspected: `/fw`, `/memory-update`.
# Paths (`/Users/x`, `~/.codex/sessions`) are not matched, because no closing backtick
# follows the name directly.
COMMAND = re.compile(r"`/([a-z][a-z0-9-]*)`")

# Not skills, but they really do exist — the host tool's built-in commands.
BUILTIN = {"clear", "hooks", "plugin", "compact", "help", "config", "codex"}

# For docs: accepts both Markdown backticks and HTML <code>. overview.html uses <code>.
DOC_COMMAND = re.compile(r"(?:`|<code>)/([a-z][a-z0-9-]*)(?:`|</code>)")


def _skill_names():
    return {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()}


class RenderedSkillCommandTest(unittest.TestCase):
    def test_every_slash_command_in_rendered_skills_exists(self):
        known = _skill_names() | BUILTIN
        unknown = []
        for base in RENDERED:
            for path in base.rglob("SKILL.md"):
                for name in COMMAND.findall(path.read_text(encoding="utf-8")):
                    if name not in known:
                        unknown.append(f"{path.relative_to(ROOT)}: /{name}")

        self.assertEqual(
            [], unknown,
            "a command that does not exist is being advertised — if a skill was added or "
            f"renamed, check both adapters together. Known skills: {sorted(known)}",
        )

    def test_the_two_names_that_slipped_through_twice_are_gone(self):
        """Regression guard. These names never existed, yet they were written in two places.

        Only what ships to users is inspected (core, plugins, docs, build.sh, README).
        `tests/` is excluded — asserting "this name must not appear" forces the test itself
        to spell the name out.
        """
        targets = [ROOT / "core", ROOT / "plugins", ROOT / "docs"]
        files = [p for base in targets for p in base.rglob("*") if p.is_file()]
        files += [ROOT / "build.sh", ROOT / "README.md", ROOT / "README.ko.md"]

        offenders = []
        for path in files:
            # ⚠️ No extension filtering. It used to look at {md, py, sh, json} only and
            # missed .html. If it reads, it is inspected — binaries drop out on their own
            # via UnicodeDecodeError.
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for dead in ("/fw-claude", "/continue-claude"):
                if dead in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {dead}")

        self.assertEqual([], offenders)


class UserFacingDocCommandTest(unittest.TestCase):
    """Whether user-facing docs advertise a **skill that does not exist**.

    The check above looks only at rendered SKILL.md. But what people actually read first is
    the README and `docs/`. When five skills were removed in PR #105, `docs/overview.html`
    stayed behind and kept introducing those five as installed features.

    HTML writes `<code>/name</code>` and Markdown writes `` `/name` `` — both are matched.
    """

    # Not skills, but they really do exist — the host tool's built-in commands.
    ALLOWED = BUILTIN

    def _doc_files(self):
        paths = [ROOT / "AGENTS.md", ROOT / "CLAUDE.md",
                 ROOT / "README.md", ROOT / "README.ko.md"]
        for base in ("docs", "project-template"):
            paths += sorted((ROOT / base).rglob("*"))
        return [p for p in paths if p.is_file() and p.suffix in {".md", ".html"}]

    def test_docs_never_advertise_a_skill_that_does_not_exist(self):
        known = _skill_names() | self.ALLOWED
        unknown = []
        for path in self._doc_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for name in DOC_COMMAND.findall(text):
                if name not in known:
                    unknown.append(f"{path.relative_to(ROOT)}: /{name}")

        self.assertEqual(
            [], unknown,
            "user-facing docs advertise a skill that does not exist — if a skill was "
            "removed or renamed, README and docs have to be fixed along with it. "
            f"Known skills: {sorted(known)}",
        )


if __name__ == "__main__":
    unittest.main()
