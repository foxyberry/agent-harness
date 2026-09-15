"""Whether the two memory skills tell each tool a project path it can actually resolve.

`memory-update` and `feedback-review` are the only skills that read and write the
project's `.claude/memory/` tree directly instead of delegating to `handoff.py`. That makes
them the only place where a wrong project root silently lands files somewhere else.

Two facts drive these checks:

- **Codex does not set `CLAUDE_PROJECT_DIR`** (measured 0.145.0 — see AGENTS.md). A rendered
  Codex SKILL.md that names it is telling the model to expand an empty variable, so
  `$CLAUDE_PROJECT_DIR/.claude/memory/_pending` reads `/.claude/memory/_pending`.
- **PATH_NOTE sends the Codex model into the skill folder**, which is a plugin cache outside
  the user repository. Any *relative* `.claude/memory/...` instruction resolves against that
  cache. This is the same cross-project blind spot as issue #3: inside this repo a relative
  path happens to work, so dogfooding never shows it.

So the invariant is structural, not textual: in the Codex rendering of these two skills,
every project-tree path must carry the project-root token. The wording of the note is not
asserted — a skill is judged by the paths it produces, not its phrasing.
"""
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CODEX_SKILLS = ROOT / "plugins" / "codex" / "skills"
CLAUDE_SKILLS = ROOT / "plugins" / "harness" / "skills"

# The two skills that touch the project memory tree by path rather than through handoff.py.
MEMORY_SKILLS = ("memory-update", "feedback-review")

# Rendered project-root tokens. They must be the *same string* the --project-dir example
# uses, or the reader sees two values for one path.
CODEX_ROOT = "<absolute-path-to-user-project>"
CLAUDE_ROOT = "$CLAUDE_PROJECT_DIR"

# Every mention of the project memory tree, whether or not it is already anchored. Matching
# starts at `.claude/memory` so an unanchored mention is caught by the absence of a prefix.
MEMORY_PATH = re.compile(r"\S*\.claude/memory/\S*")

# Bare sub-paths that name the memory tree without spelling out `.claude/memory` — the
# pending-deletion and rejected-ledger sinks that a `.claude/memory` grep misses entirely.
BARE_SUBPATH = re.compile(r"`(_pending/\S*|_rejected\.md)`")


def _skill_text(base, name):
    return (base / name / "SKILL.md").read_text(encoding="utf-8")


class CodexRenderedMemoryPathTest(unittest.TestCase):
    def test_no_codex_skill_relies_on_claude_project_dir(self):
        """Codex never sets this variable, so naming it in a Codex skill yields an empty path.

        Checked across **all** Codex skills, not just the two: the others already delegate
        to `handoff.py --project-dir`, and this keeps a future skill from reintroducing it.
        Bundled `scripts/*.py` are excluded — `handoff.py` reads the variable as one of
        several resolution sources, which is correct.
        """
        offenders = [
            str(p.relative_to(ROOT))
            for p in CODEX_SKILLS.rglob("SKILL.md")
            if "CLAUDE_PROJECT_DIR" in p.read_text(encoding="utf-8")
        ]
        self.assertEqual(
            [], offenders,
            "a Codex-rendered skill expands CLAUDE_PROJECT_DIR, which Codex does not set — "
            f"anchor the path on {CODEX_ROOT} instead",
        )

    def test_every_codex_memory_tree_path_is_anchored_on_the_project_root(self):
        """An unanchored path resolves against the skill cache, not the user project."""
        offenders = []
        for name in MEMORY_SKILLS:
            for match in MEMORY_PATH.findall(_skill_text(CODEX_SKILLS, name)):
                if CODEX_ROOT not in match:
                    offenders.append(f"{name}: {match}")

        self.assertEqual(
            [], offenders,
            "a Codex memory path is relative, so it resolves inside the plugin cache the "
            f"skill was told to cd into — prefix it with {CODEX_ROOT}",
        )

    def test_the_pending_and_rejected_sinks_are_never_named_as_bare_subpaths(self):
        """Regression guard for the sites a `.claude/memory` sweep does not see.

        `_pending/decisions/` and `_rejected.md` appeared in the promotion and deletion steps
        with no directory prefix at all. Those are exactly the write and delete sinks, so a
        wrong root there destroys drafts in one tree and writes memory into another.
        """
        offenders = []
        for name in MEMORY_SKILLS:
            for match in BARE_SUBPATH.findall(_skill_text(CODEX_SKILLS, name)):
                offenders.append(f"{name}: `{match}`")

        self.assertEqual(
            [], offenders,
            "a pending/rejected path is named without its project root — spell out "
            f"{CODEX_ROOT}/.claude/memory/... at every read, write and delete site",
        )

    def test_the_project_root_token_matches_the_project_dir_argument(self):
        """One project path must not appear under two different names.

        The skills pass the same root to `history --project-dir`. `PROJECT_ROOT` and
        `PROJECT_DIR_ARG` are separate build.sh variables, so nothing but this check stops
        them drifting into two placeholders a reader would resolve to two directories.
        Both tokens are therefore **read out of the rendered text** and compared to each
        other — asserting a hardcoded literal on each side would pass while they diverged.
        """
        for name in MEMORY_SKILLS:
            text = _skill_text(CODEX_SKILLS, name)

            arg_tokens = set(re.findall(r'--project-dir "([^"]+)"', text))
            self.assertEqual(
                1, len(arg_tokens),
                f"{name}: expected exactly one --project-dir token, got {sorted(arg_tokens)}",
            )
            arg_token = arg_tokens.pop()

            path_prefixes = {
                m.split("/.claude/memory/")[0].lstrip("`*")
                for m in MEMORY_PATH.findall(text)
            }
            self.assertEqual(
                {arg_token}, path_prefixes,
                f"{name}: the memory paths and the --project-dir example name the same "
                "directory with different tokens",
            )


class ClaudeRenderedMemoryPathTest(unittest.TestCase):
    """Claude keeps its existing behavior: `CLAUDE_PROJECT_DIR` is set, so paths anchor on it."""

    def test_claude_memory_tree_paths_stay_anchored_on_the_env_var(self):
        offenders = []
        for name in MEMORY_SKILLS:
            for match in MEMORY_PATH.findall(_skill_text(CLAUDE_SKILLS, name)):
                if CLAUDE_ROOT not in match:
                    offenders.append(f"{name}: {match}")

        self.assertEqual([], offenders)

    def test_personal_tier_is_not_anchored_on_the_project_root(self):
        """Claude auto-memory lives outside the project and must stay there.

        It is *derived* from the project path (the encoded directory name), but prefixing it
        with the project root would move the personal tier into the shared, committable tree.
        """
        text = _skill_text(CLAUDE_SKILLS, "memory-update")
        for line in text.splitlines():
            if "~/.claude/projects/" in line:
                self.assertNotIn(
                    f"{CLAUDE_ROOT}/~/.claude/projects/", line,
                    "the personal tier was anchored on the project root",
                )
        self.assertIn("~/.claude/projects/<encoded-project-path>/memory/", text)


if __name__ == "__main__":
    unittest.main()
