"""Pins that a commit-message skip marker only counts **where it is meant as a directive** (#130
follow-up).

#134 shipped the marker as a plain substring match over the whole commit message. That inverted it:
a PR whose commit body *explains* the marker skips its own retrospective. PR #134 itself did exactly
that — a 16-file source change (the hook engine, both adapters, docs, skills) that never reached the
pending queue, because one body line read:

    `[skip reflect]` 를 넣도록 명시했다. 경로 구성과 무관하게 듣는다.

Silent loss is the failure mode this whole rule set is supposed to avoid (`test_reflect_skip_scope`
records the same lesson from the path side): an over-broad skip removes the retrospective with no
warning and no failure.

## The contract

A marker is a directive in exactly two positions:

1. anywhere in the **subject** (the first line) — the familiar `[skip ci]` convention; and
2. on a **standalone body line** whose entire stripped content is the marker.

In the body, everything else is prose: backticked or quoted mentions, sentences, fenced examples.
The subject has no prose exemption beyond an exactly backticked occurrence — a subject that merely
writes about the marker still skips, which is the accepted cost of the `[skip ci]` convention. The
same contract applies to project-supplied `commit_messages` patterns, not just the engine defaults
— position, not pattern, is what separates a mark from a mention.

Both directions are pinned here. The prose cases are the bug; the directive cases are what must not
break while fixing it, because narrowing the marker too far brings the #130 loop back.

Every case runs against **all three copies of the engine** (core and both built adapters) — a stale
adapter is what the installed plugin would actually run.
"""
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK_COPIES = {
    "core": ROOT / "core" / "hooks" / "pr-merge-reflect.py",
    "claude_adapter": ROOT / "plugins" / "harness" / "hooks" / "pr-merge-reflect.py",
    "codex_adapter": ROOT / "plugins" / "codex" / "hooks" / "pr-merge-reflect.py",
}

# Ordinary source files: nothing here is harness output, so only a commit marker or a label can
# produce a skip. That keeps every case below about the marker rather than about the path rules.
SOURCE_FILES = ["core/hooks/pr-merge-reflect.py", "tests/test_reflect_marker_intent.py"]

# The real PR #134 commit body, quoted verbatim from `gh pr view 134` (first commit, the section
# that mentions the marker). Kept as the actual text — a paraphrase would stop being evidence.
PR134_BODY_EXCERPT = """## 3. 최후 방어선

`/memory-update`·`/feedback-review` SKILL.md 에 회고 산출물 커밋 메시지에
`[skip reflect]` 를 넣도록 명시했다. 경로 구성과 무관하게 듣는다.

## 검증
"""
PR134_COMMIT = (
    "fix(reflect): 회고 산출물 PR 이 다시 회고를 요구하지 않게 한다\n"
    + PR134_BODY_EXCERPT
)
# The 16 files PR #134 actually touched, as reported by `gh pr view 134 --json files`.
PR134_FILES = [
    "README.ko.md",
    "README.md",
    "core/hooks/pr-merge-reflect.py",
    "core/skills/feedback-review/SKILL.md",
    "core/skills/memory-update/SKILL.md",
    "docs/self-improvement-hooks.md",
    "plugins/codex/.codex-plugin/plugin.json",
    "plugins/codex/hooks/pr-merge-reflect.py",
    "plugins/codex/skills/feedback-review/SKILL.md",
    "plugins/codex/skills/memory-update/SKILL.md",
    "plugins/harness/.claude-plugin/plugin.json",
    "plugins/harness/hooks/pr-merge-reflect.py",
    "plugins/harness/skills/feedback-review/SKILL.md",
    "plugins/harness/skills/memory-update/SKILL.md",
    "project-template/.claude/memory/reflect-skip.json",
    "tests/test_reflect_skip_scope.py",
]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(f"pr_merge_reflect__{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENGINES = {name: _load(name, path) for name, path in HOOK_COPIES.items()}


class _Matrix(unittest.TestCase):
    """One verdict through every engine copy. Only the `gh` lookup is faked.

    The verdict logic is never restated here — `test_reflect_skip_scope.py` records why a test that
    copies the rules stops catching anything.
    """

    def assertVerdict(self, expected, project_dir, files, labels=(), commits=(), msg=""):
        details = {
            "files": list(files),
            "labels": list(labels),
            "commit_messages": list(commits),
        }
        for name, engine in ENGINES.items():
            with self.subTest(engine=name):
                with patch.object(engine, "_pr_details", return_value=details):
                    got = engine._should_skip_reflect(str(project_dir), 1)
                self.assertEqual(expected, got, msg)

    def assertSkipped(self, project_dir, commits, msg=""):
        self.assertVerdict(True, project_dir, SOURCE_FILES, commits=commits, msg=msg)

    def assertReflected(self, project_dir, commits, msg=""):
        self.assertVerdict(False, project_dir, SOURCE_FILES, commits=commits, msg=msg)


class _TempProject(_Matrix):
    """A project that participates in the hooks but supplies no `reflect-skip.json`, so every case
    below is decided by the **engine defaults**."""

    config = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        memory = self.dir / ".claude" / "memory"
        memory.mkdir(parents=True)
        if self.config is not None:
            (memory / "reflect-skip.json").write_text(
                json.dumps(self.config), encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)


class PR134RegressionTest(_Matrix):
    """The reported case, against this repository's own committed config."""

    def test_the_excerpt_still_contains_the_marker(self):
        """Without this the case below could pass while asserting about nothing."""
        self.assertIn("[skip reflect]", PR134_COMMIT,
                      "the PR #134 excerpt lost its marker — restore it from `gh pr view 134` "
                      "rather than deleting the regression")
        self.assertNotIn("[skip reflect]", PR134_COMMIT.split("\n", 1)[0],
                         "PR #134's subject never carried the marker; if this excerpt does, it is "
                         "no longer the reported case")

    def test_pr134_is_reflected(self):
        self.assertVerdict(
            False, ROOT, PR134_FILES, commits=[PR134_COMMIT],
            msg="PR #134 — 16 files of real source, hooks and docs — skipped its own "
                "retrospective because a body line explains the marker in prose. The marker is "
                "being matched as a bare substring again")

    def test_the_same_pr_with_a_real_directive_is_skipped(self):
        """The discriminating twin: identical files, the marker moved into directive position.
        Without it, 'reflected' could mean the marker stopped working entirely."""
        self.assertVerdict(
            True, ROOT, PR134_FILES,
            commits=[PR134_COMMIT.split("\n", 1)[0] + " [skip reflect]\n" + PR134_BODY_EXCERPT])


class DirectivePositionsTest(_TempProject):
    """What must keep skipping — the documented escape hatch for a rule-promotion PR."""

    def test_subject_marker(self):
        for subject in ("docs: promote lesson [skip reflect]",
                        "[skip reflect] docs: promote lesson",
                        "docs: promote lesson (skip-reflect)",
                        "docs: promote lesson — no-reflect"):
            with self.subTest(subject=subject):
                self.assertSkipped(self.dir, [subject])

    def test_subject_marker_with_an_ordinary_body(self):
        self.assertSkipped(self.dir, ["docs: promote lesson [skip reflect]\n\nPromotes #130.\n"])

    def test_standalone_body_line(self):
        for body in ("[skip reflect]", "  [skip reflect]  ", "skip-reflect", "no-reflect"):
            with self.subTest(body=body):
                self.assertSkipped(self.dir, [f"docs: promote lesson\n\nCloses #130.\n\n{body}\n"])

    def test_case_is_ignored(self):
        for commit in ("docs: promote [SKIP REFLECT]",
                       "docs: promote\n\n[Skip Reflect]\n",
                       "docs: promote SKIP-REFLECT"):
            with self.subTest(commit=commit):
                self.assertSkipped(self.dir, [commit])

    def test_any_commit_in_the_pr_carries_the_directive(self):
        """A PR is a set of commits; the marker on one of them marks the PR."""
        self.assertSkipped(self.dir, ["fix: groundwork\n\nNo marker here.\n",
                                      "docs: promote lesson [skip reflect]"])

    def test_labels_are_unaffected(self):
        """Label matching does not route through the message gate."""
        self.assertVerdict(True, self.dir, SOURCE_FILES, labels=["skip-reflect"])
        self.assertVerdict(True, self.dir, SOURCE_FILES, labels=["No-Reflect"])


class FencedExamplesTest(_TempProject):
    """A fenced example of the marker is documentation, so it must not skip — and the fence has to
    stay closed until it is *really* closed.

    The first implementation tracked fences with a boolean toggle. Codex found three commit bodies
    where that releases the block early and the example below it becomes a directive, losing the
    retrospective for a genuine PR. Each is pinned here by shape, because they fail for three
    different reasons: wrong fence character, shorter run, and text after the run.
    """

    def test_a_closed_fenced_example(self):
        for fence in ("```", "~~~"):
            with self.subTest(fence=fence):
                self.assertReflected(
                    self.dir,
                    [f"docs: document the marker\n\nUse it like this:\n\n"
                     f"{fence}\n[skip reflect]\n{fence}\n\nThat is all.\n"])

    def test_a_foreign_fence_character_does_not_close(self):
        self.assertReflected(
            self.dir, ["docs: explain markers\n\n```text\n~~~\n[skip reflect]\n```"],
            msg="`~~~` inside a ``` block is block content, not a closing fence")

    def test_a_shorter_run_does_not_close(self):
        self.assertReflected(
            self.dir, ["docs: explain markers\n\n````text\n```\n[skip reflect]\n````"],
            msg="a closing fence needs a run at least as long as the opener")

    def test_a_run_with_trailing_text_does_not_close(self):
        self.assertReflected(
            self.dir,
            ["docs: explain markers\n\n```text\n``` not a closing fence\n[skip reflect]\n```"],
            msg="a closing fence carries nothing but whitespace after the run")

    def test_a_real_close_releases_the_rest_of_the_body(self):
        """The other direction: over-tightening the close rule would swallow every later directive
        and bring the #130 loop back."""
        for body in ("```\n[skip reflect]\n```\n\n[skip reflect]\n",
                     "~~~text\n[skip reflect]\n~~~\n\n[skip reflect]\n",
                     "```\n[skip reflect]\n`````\n\n[skip reflect]\n",
                     "```\n[skip reflect]\n```   \n\n[skip reflect]\n",
                     # Two blocks back to back: the state must not drift by one block and
                     # swallow the directive that follows them.
                     "```\n[skip reflect]\n```\n```\n[skip reflect]\n```\n\n[skip reflect]\n",
                     # An unclosed fence hides what comes after it, never what came before.
                     "[skip reflect]\n\n```\nstill open\n"):
            with self.subTest(body=body):
                self.assertSkipped(
                    self.dir, [f"docs: promote lesson\n\n{body}"],
                    msg="the fence closed, so the standalone marker after it is a directive")


class ProseMentionsTest(_TempProject):
    """What must stop skipping — every one of these is a commit *writing about* the marker."""

    def test_the_pr134_shape_backticked_with_trailing_text(self):
        self.assertReflected(
            self.dir,
            ["fix(reflect): close the loop\n\n"
             "`[skip reflect]` 를 넣도록 명시했다. 경로 구성과 무관하게 듣는다.\n"])

    def test_a_sentence_mentioning_the_marker(self):
        for body in ("Commits should carry [skip reflect] when promoting a lesson.",
                     "The skip-reflect label does the same thing.",
                     "We considered no-reflect and rejected it."):
            with self.subTest(body=body):
                self.assertReflected(self.dir, [f"fix: real work\n\n{body}\n"])

    def test_a_quoted_line(self):
        self.assertReflected(
            self.dir,
            ["fix: real work\n\nThe review said:\n\n> [skip reflect]\n\nWe disagreed.\n"])

    def test_a_backticked_standalone_line(self):
        self.assertReflected(
            self.dir, ["docs: show the marker\n\n`[skip reflect]`\n"],
            msg="a line that quotes the marker in backticks is showing it, not using it")

    def test_a_backticked_subject_mention(self):
        self.assertReflected(
            self.dir, ["docs: explain `[skip reflect]` in the skills"],
            msg="the subject is quoting the marker, not carrying it")

    def test_an_empty_headline_does_not_promote_the_body(self):
        """`_pr_details` joins headline and body; the join must not slide a prose body line into
        subject position when the headline is empty."""
        self.assertReflected(
            self.dir, ["\n`[skip reflect]` is the marker this PR documents.\n"])

    def test_substring_collisions_still_do_not_match(self):
        """Pre-existing behaviour, restated because the matcher moved."""
        for subject in ("fix: improve no-reflection handling",
                        "fix: rename skip-reflected to skipped"):
            with self.subTest(subject=subject):
                self.assertReflected(self.dir, [subject])


class ProjectPatternsFollowTheSameContractTest(_TempProject):
    """A project's own `commit_messages` patterns are marks, not mentions, in the same two places.

    Applying the contract only to the engine defaults would leave a project's custom marker
    carrying the #134 bug while the built-in one is immune — the fix would be half-done, and which
    half you got would depend on where the pattern was configured.
    """

    config = {"commit_messages": ["[no-retro]", "retro-exempt", "  [padded-retro]  "]}

    def test_a_custom_pattern_in_directive_position_skips(self):
        for commit in ("chore: rotate keys [no-retro]",
                       "chore: rotate keys\n\n[no-retro]\n",
                       "chore: rotate keys (retro-exempt)"):
            with self.subTest(commit=commit):
                self.assertSkipped(self.dir, [commit])

    def test_a_custom_pattern_in_prose_does_not(self):
        self.assertReflected(
            self.dir,
            ["feat: add the marker\n\nProjects can configure [no-retro] as an exemption.\n"],
            msg="a project pattern is narrowed to directive positions exactly like the defaults; "
                "documented in docs/self-improvement-hooks.md")

    def test_a_custom_pattern_in_a_fenced_example_does_not(self):
        """The fence rules are part of the contract, not a property of the built-in markers."""
        self.assertReflected(
            self.dir,
            ["docs: document the project marker\n\n```text\n~~~\n[no-retro]\n```"])

    def test_a_padded_pattern_is_used_exactly_as_stored(self):
        """The loader keeps a project's pattern verbatim (it only filters empty ones), and this
        gate does not trim it either.

        So `"  [padded-retro]  "` still matches from the subject, where the old substring rules are
        unchanged, but a standalone body line is compared **trimmed line against literal pattern**
        and therefore does not match. Trimming the pattern here would make the body line match
        something the old whole-message substring rule never matched — a *new* skip, and this
        change is only allowed to move in the direction of more retrospectives.
        """
        # The padding is part of the pattern, so the subject has to carry it too — the subject
        # rules are the pre-existing ones, unchanged by this fix.
        self.assertSkipped(self.dir, ["chore: rotate keys   [padded-retro]  (#1)"])
        self.assertReflected(self.dir, ["chore: rotate keys\n\n[padded-retro]\n"])

    def test_the_engine_defaults_still_apply_alongside(self):
        """The loader extends rather than replaces, so the built-in marker keeps working here."""
        self.assertSkipped(self.dir, ["chore: rotate keys [skip reflect]"])


class PrDetailsProductionPathTest(unittest.TestCase):
    """The one production line the matrix above cannot see: `_pr_details` itself.

    Every other case here fakes `_pr_details` out, so the join it performs — headline, newline,
    body, **not stripped** — is exercised by nothing. Restoring the `.strip()` that used to be
    there kept the whole suite green while silently promoting a body's first line into subject
    position, where prose counts as a directive. So this case fakes `subprocess.run` instead and
    drives the real `gh` parsing.
    """

    GH_JSON = json.dumps({
        "files": [{"path": p} for p in SOURCE_FILES],
        "labels": [],
        "commits": [{
            # An empty headline is what `gh` reports for a commit whose message starts with a
            # blank line (`--cleanup=verbatim`). Rare, but it is the shape that breaks.
            "messageHeadline": "",
            "messageBody": "`[skip reflect]` is the marker this PR documents.\n\nCloses #130.\n",
        }],
    })

    class _Result:
        returncode = 0

        def __init__(self, stdout):
            self.stdout = stdout

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        (self.dir / ".claude" / "memory").mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def test_an_empty_headline_keeps_line_zero_empty(self):
        for name, engine in ENGINES.items():
            with self.subTest(engine=name):
                with patch.object(engine.subprocess, "run",
                                  return_value=self._Result(self.GH_JSON)):
                    details = engine._pr_details(str(self.dir), 1)
                message = details["commit_messages"][0]
                self.assertEqual("", message.split("\n")[0],
                                 "the headline/body join was stripped again — the body's first "
                                 "line is now read as the subject")

    def test_the_verdict_from_the_real_gh_parsing_is_reflect(self):
        """The same shape end to end, so the join and the gate are pinned together."""
        for name, engine in ENGINES.items():
            with self.subTest(engine=name):
                with patch.object(engine.subprocess, "run",
                                  return_value=self._Result(self.GH_JSON)):
                    self.assertFalse(engine._should_skip_reflect(str(self.dir), 1))


class TruncatedHeadlineTest(unittest.TestCase):
    """A long subject splits the marker in `gh pr view` output (#148).

    GitHub cuts `messageHeadline` at a character boundary and puts `…` on both sides, so the join in
    `_pr_details` read `[ski…` / `…p reflect]` and a retrospective-output PR asked for its own
    retrospective. The fix fetches the untruncated `commit.message` from the REST API, keyed by sha.

    The fixture is PR 445 of another (private) repository, commit a353ca8, quoted verbatim from
    `gh pr view <n> --json commits` and `gh api repos/{owner}/{repo}/pulls/<n>/commits`, cut after
    the first bullet — the rest is a list and a footer naming the author's machine, which does not
    belong in a public repo.
    """

    SHA = "a353ca8ddf56ca2550db92ec3ccc7293019dcf9d"
    SUBJECT = ("[docs/memory-retrospective-20260916] docs: 회고 결과를 규칙과 공유 메모리로 반영 "
               "[skip reflect]")
    BULLET = "- git-pr 에 리뷰 게이트(2.5) 추가 — #433·#435·#440 에서 네 번 되물음"
    VIEW_COMMIT = {
        "oid": SHA,
        "messageHeadline": ("[docs/memory-retrospective-20260916] docs: 회고 결과를 규칙과 공유 "
                            "메모리로 반영 [ski…"),
        "messageBody": "…p reflect]\n\n" + BULLET,
    }
    FULL_MESSAGE = SUBJECT + "\n\n" + BULLET + "\n"

    class _Result:
        def __init__(self, stdout, returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        (self.dir / ".claude" / "memory").mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def _gh(self, commits, api_rows=(), api_rc=0, api_stdout=None):
        """Fake `subprocess.run` for both `gh` calls; records the argv of every call."""
        calls = []
        view = json.dumps({"files": [{"path": p} for p in SOURCE_FILES], "labels": [],
                           "commits": commits})
        # `gh api --jq` prints one compact object per line.
        api = api_stdout if api_stdout is not None else "".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in api_rows)

        def run(cmd, **_kw):
            calls.append(cmd)
            if cmd[:2] == ["gh", "api"]:
                return self._Result(api, api_rc)
            return self._Result(view)
        return run, calls

    def _each_engine(self, commits, api_rows=(), api_rc=0, api_stdout=None):
        for name, engine in ENGINES.items():
            run, calls = self._gh(commits, api_rows, api_rc, api_stdout)
            with self.subTest(engine=name):
                with patch.object(engine.subprocess, "run", side_effect=run):
                    yield engine, calls

    def test_the_fixture_is_actually_split(self):
        joined = self.VIEW_COMMIT["messageHeadline"] + "\n" + self.VIEW_COMMIT["messageBody"]
        self.assertNotIn("[skip reflect]", joined)

    def test_pr445_is_skipped_through_the_full_message(self):
        rows = [{"sha": self.SHA, "message": self.FULL_MESSAGE}]
        for engine, calls in self._each_engine([self.VIEW_COMMIT], rows):
            self.assertTrue(engine._should_skip_reflect(str(self.dir), 445))
            api = [c for c in calls if c[:2] == ["gh", "api"]]
            self.assertEqual(1, len(api))
            # One page covers every commit `gh pr view` returns (its first 100); paginating
            # would only let a later-page failure discard this one.
            self.assertNotIn("--paginate", api[0])
            self.assertIn("repos/{owner}/{repo}/pulls/445/commits?per_page=100", api[0])

    def test_rows_are_matched_by_sha_not_position(self):
        """Several rows on the one page: the truncated commit is replaced by its own row, and an
        unrelated commit listed after it does not overwrite that replacement."""
        other = "chore: unrelated commit listed last\n"
        rows = [{"sha": "0" * 40, "message": "chore: listed first\n"},
                {"sha": self.SHA, "message": self.FULL_MESSAGE},
                {"sha": "1" * 40, "message": other}]
        for engine, _calls in self._each_engine([self.VIEW_COMMIT], rows):
            details = engine._pr_details(str(self.dir), 445)
            self.assertEqual([self.FULL_MESSAGE], details["commit_messages"])
            self.assertTrue(engine._should_skip_reflect(str(self.dir), 445))

    def test_an_untruncated_pr_makes_no_extra_request(self):
        commit = {"oid": self.SHA, "messageHeadline": "docs: short [skip reflect]",
                  "messageBody": ""}
        for engine, calls in self._each_engine([commit]):
            self.assertTrue(engine._should_skip_reflect(str(self.dir), 1))
            self.assertEqual([], [c for c in calls if c[:2] == ["gh", "api"]])

    def test_an_api_failure_keeps_the_truncated_form_and_reflects(self):
        for engine, _calls in self._each_engine([self.VIEW_COMMIT], api_rc=1):
            self.assertFalse(engine._should_skip_reflect(str(self.dir), 445))

    def test_unparseable_api_output_reflects(self):
        for engine, _calls in self._each_engine([self.VIEW_COMMIT], api_stdout="not json\n"):
            self.assertFalse(engine._should_skip_reflect(str(self.dir), 445))

    def test_a_sha_the_api_does_not_list_is_not_replaced(self):
        """A commit the lookup does not list (say, another repo's PR) is not replaced."""
        rows = [{"sha": "f" * 40, "message": self.FULL_MESSAGE}]
        for engine, _calls in self._each_engine([self.VIEW_COMMIT], rows):
            details = engine._pr_details(str(self.dir), 445)
            self.assertEqual(
                self.VIEW_COMMIT["messageHeadline"] + "\n" + self.VIEW_COMMIT["messageBody"],
                details["commit_messages"][0])
            self.assertFalse(engine._should_skip_reflect(str(self.dir), 445))

    def test_the_full_message_is_still_position_gated(self):
        """A long subject whose full body only *explains* the marker stays reflectable, and an empty
        first line from the full message is not filled in from the body (#150)."""
        cases = [
            ("fix: " + "x" * 80 + "\n\nCommits should carry [skip reflect] when promoting.\n",
             "fix: " + "x" * 60 + "…", "…" + "x" * 20),
            ("\n[skip reflect] is what this PR documents, in a sentence.\n",
             "", "…"),
            ("docs: " + "y" * 80 + "\n\n```\n[skip reflect]\n```\n",
             "docs: " + "y" * 60 + "…", "…" + "y" * 20),
        ]
        for full, headline, body in cases:
            commit = {"oid": self.SHA, "messageHeadline": headline, "messageBody": body}
            rows = [{"sha": self.SHA, "message": full}]
            for engine, _calls in self._each_engine([commit], rows):
                details = engine._pr_details(str(self.dir), 1)
                self.assertEqual(full, details["commit_messages"][0])
                self.assertFalse(engine._should_skip_reflect(str(self.dir), 1))

    def test_a_standalone_body_marker_in_the_full_message_skips(self):
        full = "docs: " + "z" * 80 + "\n\nPromotes lessons.\n\n[skip reflect]\n"
        commit = {"oid": self.SHA, "messageHeadline": "docs: " + "z" * 60 + "…",
                  "messageBody": "…" + "z" * 20 + "\n\nPromotes lessons."}
        rows = [{"sha": self.SHA, "message": full}]
        for engine, _calls in self._each_engine([commit], rows):
            self.assertTrue(engine._should_skip_reflect(str(self.dir), 1))


class TruncatedHeadlineCustomPatternTest(TruncatedHeadlineTest):
    """The same repair serves a project's own `commit_messages` pattern (#149 config)."""

    SUBJECT = "chore: " + "w" * 80 + " [no-retro]"
    VIEW_COMMIT = {"oid": TruncatedHeadlineTest.SHA,
                   "messageHeadline": "chore: " + "w" * 80 + " [no-r…",
                   "messageBody": "…etro]"}
    FULL_MESSAGE = SUBJECT + "\n"

    def setUp(self):
        super().setUp()
        (self.dir / ".claude" / "memory" / "reflect-skip.json").write_text(
            json.dumps({"commit_messages": ["[no-retro]"]}), encoding="utf-8")

    def test_the_fixture_is_actually_split(self):
        joined = self.VIEW_COMMIT["messageHeadline"] + "\n" + self.VIEW_COMMIT["messageBody"]
        self.assertNotIn("[no-retro]", joined)


if __name__ == "__main__":
    unittest.main()
