"""Checks that documents do not get quietly buried.

Dropping one more file into `docs/` is easy; adding the link in the README is easy to
forget. Without a link the document exists **only for someone who clones the repository and
browses the tree**. That actually happened here: `decision-mining.md` and
`public-release-audit.md` spent months that way — not deleted, not wrong, just not linked
from anywhere.

Two things are pinned down.

1. Every file under `docs/` is linked from **both README.md and README.ko.md**.
2. Both READMEs link **the same set of documents**. Fixing only one lets the translation
   fall behind, which is a mistake this repository has repeatedly made (when the same fact
   lives in two places, one of them gets missed).

Why only `docs/`: that is where growth happens. Most of what lives under
`project-template/` is **example data** (routes, rules, memory samples) rather than
documentation, so requiring links for all of it would mean editing the README every time
data is added. Hence only the human-readable root documents are pinned by name.
"""
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
READMES = ["README.md", "README.ko.md"]

# Root documents that must be linked — pinned by name (this list rarely grows).
ROOT_DOCS = ["AGENTS.md", "SECURITY.md"]

# Extract only the destination of a markdown link: [text](target)
LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")


def _linked_targets(readme_name):
    text = (ROOT / readme_name).read_text(encoding="utf-8")
    return {t.split("#", 1)[0] for t in LINK_TARGET.findall(text)}


def _doc_files():
    """Human-readable files under `docs/`. If none are found the tests pass vacuously, so that is checked too."""
    return sorted(
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "docs").rglob("*")
        if p.is_file() and p.suffix in {".md", ".html"}
    )


class DocLinkCoverageTest(unittest.TestCase):
    def test_fixture_is_not_empty(self):
        """If `docs/` cannot be found, every check below passes vacuously."""
        self.assertGreater(len(_doc_files()), 1,
                           "could not read docs/ — the checks below would be meaningless")

    def test_every_doc_is_linked_from_both_readmes(self):
        docs = _doc_files()
        missing = []
        for readme in READMES:
            linked = _linked_targets(readme)
            for doc in docs + ROOT_DOCS:
                if doc not in linked:
                    missing.append(f"{readme}: {doc}")

        self.assertEqual(
            [], missing,
            "A document is not linked from a README — when you add one, put it in the "
            "document tables of **both** README.md and README.ko.md. Otherwise it only "
            "exists for people browsing the tree.",
        )

    def test_both_readmes_link_the_same_docs(self):
        """Fixing only one side lets the translation fall behind — the same fact in two places means one gets missed."""
        docs = set(_doc_files()) | set(ROOT_DOCS)
        en = _linked_targets("README.md") & docs
        ko = _linked_targets("README.ko.md") & docs

        self.assertEqual(
            en, ko,
            "The two READMEs link different sets of documents — "
            f"English only: {sorted(en - ko)} / Korean only: {sorted(ko - en)}",
        )

    def test_linked_repo_paths_actually_exist(self):
        """A dead link is another way to lose a document — renaming quietly breaks it."""
        dead = []
        for readme in READMES:
            for target in _linked_targets(readme):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                if not (ROOT / target).exists():
                    dead.append(f"{readme}: {target}")

        self.assertEqual([], dead, "an in-repository link in a README is broken")


if __name__ == "__main__":
    unittest.main()
