"""The mechanism that stops a rejected draft from being recreated in the next session (issue #109).

Rejecting a draft deletes the file in `_pending/`. **The fact that it was rejected is then recorded
nowhere**, so the next session reads the same transcript, extracts the same lesson, and creates the
same draft again.

The fix is to put `_rejected.md` into the retrospection prompt -- the same approach
`_decisions_index` uses when it feeds in existing ADRs to get chain proposals. The LLM is already
making the similarity judgement.

Note on language: the prompt text the harness *generates* is English, but `_rejected.md` is a
user-maintained ledger that may be in any language. The parse is deliberately language-agnostic
(lines starting with `- `), and the fixtures below keep Korean entries to pin that.
"""
import importlib.util
import pathlib
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).parents[1] / "core" / "hooks" / "reflect.py"
SPEC = importlib.util.spec_from_file_location("reflect", SCRIPT)
reflect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reflect)


class RejectedIndexTest(unittest.TestCase):
    def _project(self, body=None):
        tmp = tempfile.mkdtemp()
        memory = pathlib.Path(tmp) / ".claude" / "memory"
        memory.mkdir(parents=True)
        if body is not None:
            (memory / "_rejected.md").write_text(body, encoding="utf-8")
        return tmp

    def test_no_file_is_not_an_error(self):
        """Most projects never copied the template -- this has to pass through quietly."""
        self.assertEqual(reflect.NONE_YET, reflect._rejected_index(self._project()))

    def test_file_with_only_prose_counts_as_empty(self):
        """A new file with only a heading and no entries. Prose must not be mistaken for entries."""
        project = self._project("# Rejected drafts\n\nCandidates decided against are listed here.\n")
        self.assertEqual(reflect.NONE_YET, reflect._rejected_index(project))

    def test_entries_are_returned_for_the_prompt(self):
        project = self._project(
            "# Rejected drafts\n\nExplanatory paragraph.\n\n"
            "- `use-tabs` — .editorconfig already enforces it (2026-08-18)\n"
            "- `short-titles` — a one-off remark (2026-08-18)\n"
        )
        out = reflect._rejected_index(project)
        self.assertIn("use-tabs", out)
        self.assertIn("short-titles", out)
        self.assertNotIn("Explanatory paragraph", out)

    def test_a_korean_ledger_still_parses(self):
        """Legacy compatibility: ledgers written before the runtime spoke English.

        The entries are user-written prose in Korean around a heading that is Korean too. The parser
        keys on `- ` only, so these must keep flowing into the prompt verbatim -- if translation had
        introduced any language assumption, existing projects would silently lose their whole
        rejection history and start regenerating drafts people already threw away.
        """
        project = self._project(
            "# 폐기한 초안\n\n설명 문단.\n\n"
            "- `use-tabs` — .editorconfig 가 이미 강제 (2026-08-18)\n"
            "- `short-titles` — 한 번뿐인 지적 (2026-08-18)\n"
        )
        out = reflect._rejected_index(project)
        self.assertIn("- `use-tabs` — .editorconfig 가 이미 강제 (2026-08-18)", out)
        self.assertIn("- `short-titles` — 한 번뿐인 지적 (2026-08-18)", out)
        self.assertNotIn("설명 문단", out, "prose was mistaken for an entry")

    def test_a_korean_ledger_with_only_prose_is_still_empty(self):
        """The "no entries" verdict must not depend on the language of the prose either."""
        project = self._project("# 폐기한 초안\n\n안 남기기로 한 후보를 여기 적는다.\n")
        self.assertEqual(reflect.NONE_YET, reflect._rejected_index(project))

    def test_oldest_entries_drop_first_when_capped(self):
        """The file is append-only, so the tail is newest. On overflow the **old head** is dropped
        -- the more recently something was rejected, the likelier it is to be generated again."""
        rows = [f"- `lesson-{i}` — reason (2026-08-18)" for i in range(60)]
        project = self._project("# Rejected\n\n" + "\n".join(rows) + "\n")
        out = reflect._rejected_index(project)
        self.assertNotIn("`lesson-0`", out, "the oldest entry survived")
        self.assertIn("`lesson-59`", out, "the most recent entry was cut")
        self.assertIn("older entries omitted", out, "the truncation was not announced")


class CommentedExampleTest(unittest.TestCase):
    """Does an example inside a comment **leak in as a real rejection record?**

    The parser treats lines starting with `- ` as entries. When a person writes examples into the
    file they naturally wrap them in `<!-- ... -->`, but **a line-oriented parser does not see
    comments.** Rejections that never happened would then be injected into every retrospection
    prompt, silently blocking similar lessons.

    `_decisions_index` already prevents the same failure -- it filters out README and EXAMPLE files
    to "stop examples in a freshly copied project being injected as real existing chains". This
    checks the same bug was not reintroduced on the new path.
    """

    def _index(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            memory = pathlib.Path(tmp) / ".claude" / "memory"
            memory.mkdir(parents=True)
            (memory / "_rejected.md").write_text(body, encoding="utf-8")
            return reflect._rejected_index(tmp)

    def test_commented_out_examples_are_not_entries(self):
        out = self._index(
            "# Rejected retrospection drafts\n\n"
            "<!-- An example. In practice you delete this and start fresh.\n"
            "- `use-tabs-not-spaces` — .editorconfig already enforces it (2026-08-18)\n"
            "-->\n"
        )
        self.assertEqual(reflect.NONE_YET, out,
                         f"an example inside a comment leaked in as a real record:\n{out}")

    def test_commented_out_examples_in_a_korean_template_are_not_entries(self):
        """The shipped Korean template wraps its example the same way -- keep that case covered."""
        out = self._index(
            "# 폐기한 회고 초안\n\n"
            "<!-- 예시다. 실제로는 지우고 시작한다.\n"
            "- `use-tabs-not-spaces` — .editorconfig 가 이미 강제 (2026-08-18)\n"
            "-->\n"
        )
        self.assertEqual(reflect.NONE_YET, out,
                         f"an example inside a comment leaked in as a real record:\n{out}")

    def test_real_entries_around_a_comment_still_count(self):
        """Stripping comments must not take real entries with it."""
        out = self._index(
            "# Rejected\n\n"
            "- `real-one` — really rejected (2026-08-18)\n"
            "<!-- note: the line below is an example\n- `fake-one` — example (2026-08-18)\n-->\n"
            "- `real-two` — really rejected (2026-08-18)\n"
        )
        self.assertIn("real-one", out)
        self.assertIn("real-two", out)
        self.assertNotIn("fake-one", out)


class RenderedSkillTest(unittest.TestCase):
    """Is it wired into the interactive path (`/memory-update`) as well?

    Automatic retrospection is off by default, so the place drafts actually get regenerated is the
    **interactive path** -- `/memory-update` re-extracts them from the transcript every time. Fixing
    only reflect.py would leave the part that actually hurts untouched. Editing core without running
    build.sh is also caught here.
    """

    ADAPTERS = ("harness", "codex")

    def _rendered(self, adapter):
        return (pathlib.Path(__file__).parents[1] / "plugins" / adapter
                / "skills" / "memory-update" / "SKILL.md").read_text(encoding="utf-8")

    def test_both_adapters_read_and_write_the_rejection_list(self):
        for adapter in self.ADAPTERS:
            text = self._rendered(adapter)
            with self.subTest(adapter=adapter, path="read"):
                self.assertIn("_rejected.md", text)
                self.assertIn("exclude it from the candidates", text,
                              "nothing tells the dedup step to use the rejection list")
            with self.subTest(adapter=adapter, path="write"):
                self.assertIn("append", text,
                              "nothing tells it to record rejections — the list never fills up")

    def test_it_is_not_presented_as_a_permanent_ban(self):
        for adapter in self.ADAPTERS:
            with self.subTest(adapter=adapter):
                self.assertIn("not a ban list", self._rendered(adapter))


class PromptWiringTest(unittest.TestCase):
    """Catches the wiring gap where normalisation happens but **nothing reaches the prompt**.

    Testing only the function misses "it reads fine but nobody uses it" -- which happened twice in
    this repository.
    """

    def test_prompt_tells_the_model_to_skip_rejected_lessons(self):
        self.assertIn(reflect.REJECTED_SECTION, reflect.PROMPT,
                      "the prompt never names the rejection list — filling the list in would not "
                      "make the model look at it")

    def test_the_prompt_and_the_assembled_section_use_the_same_name(self):
        """The instruction points at a section heading assembled elsewhere in main().

        If the two drift apart the prompt tells the model to consult a section that does not exist
        under that name, and the failure is invisible: the LLM just ignores the list.
        """
        source = SCRIPT.read_text(encoding="utf-8")
        assembly = source[source.index("prompt = ("):source.index("text = BACKENDS[backend]")]
        self.assertIn("REJECTED_SECTION", assembly,
                      "the assembled heading does not use the shared constant")
        self.assertIn("DECISIONS_SECTION", assembly,
                      "the assembled heading does not use the shared constant")
        self.assertIn(reflect.DECISIONS_SECTION, reflect.PROMPT + reflect.ADR_DRAFT_CONTRACT,
                      "nothing tells the model to consult the decision chain index")

    def test_prompt_does_not_turn_it_into_a_permanent_ban(self):
        """Blocking something forever because it was rejected once is its own bug -- if it recurs
        and gains value it has to be raisable again."""
        self.assertIn("it is not a ban list", reflect.PROMPT)

    def test_rejected_index_is_assembled_into_the_prompt(self):
        source = SCRIPT.read_text(encoding="utf-8")
        assembly = source[source.index("prompt = ("):source.index("text = BACKENDS[backend]")]
        self.assertIn("_rejected_index(project_dir)", assembly,
                      "_rejected_index never made it into the prompt assembly")


class DraftLanguageContractTest(unittest.TestCase):
    """Both draft generators must ask for English prose while leaving source text alone.

    The harness's own runtime speaks English, but the material it reads does not: transcripts and
    commit messages in this project are often Korean. Without an explicit instruction the model
    mirrors the source language, and drafts land in `_pending/` in a different language from the
    memory they will be promoted into. The other half matters more -- quoted evidence, code, paths
    and identifiers must stay verbatim, or a draft's Evidence section stops matching the repository
    it cites.

    `reflect` and `mine` are two generators feeding one promotion path, so the contract is asserted
    on both. Purely offline: the prompt strings are inspected, no backend is called.
    """

    @classmethod
    def setUpClass(cls):
        mine_spec = importlib.util.spec_from_file_location(
            "mine", SCRIPT.parent / "mine.py")
        cls.mine = importlib.util.module_from_spec(mine_spec)
        mine_spec.loader.exec_module(cls.mine)

    def prompts(self):
        return {"reflect.PROMPT": reflect.PROMPT, "mine.MINE_PROMPT": self.mine.MINE_PROMPT}

    def test_both_prompts_ask_for_english_draft_prose(self):
        for name, prompt in self.prompts().items():
            with self.subTest(prompt=name):
                self.assertIn("in **English**", prompt,
                              "the generator does not ask for English draft prose — drafts will "
                              "mirror the source language")
                self.assertIn("even when the source", prompt,
                              "the instruction does not cover non-English source material")

    def test_both_prompts_forbid_translating_quoted_source(self):
        for name, prompt in self.prompts().items():
            with self.subTest(prompt=name):
                self.assertIn("do not translate them", prompt,
                              "nothing stops the model rewriting quoted source text")
                for kept in ("quoted evidence", "code", "file paths", "identifiers"):
                    self.assertIn(kept, prompt,
                                  f"the instruction does not protect {kept} from translation")


if __name__ == "__main__":
    unittest.main()
