#!/usr/bin/env python3
"""Does the handoff ever falsely claim to be **committed**? (issue #133)

Regression target: `save` baked "this file is **committed**" into the body without
committing anything, and `load` titled the section "committed handoff" purely because the
file existed. Untracked, staged and modified-after-commit all looked "committed".

Three invariants are protected:
  1) Say 'committed' only when the content really matches HEAD (a failed git lookup is
     'cannot tell').
  2) The saved body never carries a state claim that turns false on either side of a commit.
  3) The git commands we print run against the target repository **regardless of cwd**.

The tests run on a real temporary git repository. The outside world is blocked instead:
gh PR lookups (network) and `~/.claude`/`~/.codex` (the user's own session logs) — reading
someone else's logs or touching the network would make results depend on the environment.
"""
import importlib.util
import os
import re
import shlex
import subprocess
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "handoff", ROOT / "core" / "scripts" / "handoff.py"
)
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)

# Derived from the labels themselves so a reworded label cannot silently slip past this
# guard. Substring matching on the bare word "committed" would be useless — "not committed"
# contains it — so the **whole** label is what must be absent.
COMMITTED_LABELS = tuple(
    handoff.HANDOFF_STATE_LABELS[key]
    for key in ("committed-clean", "committed-modified", "committed-untracked")
)
# Plus one literal phrase, so a relabel that keeps the dict consistent but starts calling
# uncommitted files "committed handoff" still fails.
COMMITTED_CLAIMS = COMMITTED_LABELS + ("committed handoff",)

# A banner an older version baked into saved files. Kept verbatim in Korean: this is
# historical file content that still exists in real repositories, not generated output.
LEGACY_BANNER = "> ⚠️ 이 파일은 **커밋됨**. 이어받는 사람/툴은 먼저 이걸 읽고"


def _strip_emphasis(text):
    """Flatten Markdown decoration so a status claim cannot hide inside it.

    The #133 claim shipped as `이 파일은 **커밋됨**`, and its direct English form is
    `This file is **committed**`. A raw substring search for the sentence misses both,
    because the emphasis markers sit between the words. Blockquote markers and line
    wrapping can split a claim the same way, so those are flattened too.
    """
    lines = [re.sub(r"^\s*>+\s?", "", line) for line in (text or "").splitlines()]
    flat = re.sub(r"[*_`~]", "", " ".join(lines))
    return re.sub(r"\s+", " ", flat).strip().lower()


# Status assertions that go stale the moment the file is (or is not) committed. Matched
# against the emphasis-stripped body. Instructions ("it has to be committed and pushed")
# and pointers ("check git for the real state") are deliberately absent from this list —
# they stay true on both sides of a commit.
FORBIDDEN_STATUS_CLAIMS = (
    "this file is committed",
    "this file is not committed",
    "this file is uncommitted",
    "this file is already committed",
    "this file has been committed",
    "this file was committed",
    "not committed",
    "already committed",
    "이 파일은 커밋됨",       # the original #133 claim, emphasis stripped
    "이 파일은 커밋되",        # covers 커밋되었다 / 커밋되지 않았다 phrasings
)

FAKE_FACTS = {
    "branch": "fake",
    "status": "(none)",
    "stat_unstaged": "(none)",
    "stat_staged": "(none)",
    "ahead": "(none)",
    "pr": "(none, or lookup failed)",
}


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True,
                   capture_output=True, text=True)


class _Args:
    """Stand-in for argparse.Namespace — only the attributes cmd_save/cmd_load read."""

    def __init__(self, **kw):
        self.project_dir = None
        self.agent = "claude"
        self.summary = self.done = self.next = self.verify = None
        self.deep = False
        self.transcript = None
        for k, v in kw.items():
            setattr(self, k, v)


class HandoffCommitStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)
        # A cwd outside the repo that doubles as a fake HOME, so the real user home is
        # never touched.
        self.outside = tempfile.TemporaryDirectory()
        self.elsewhere = os.path.realpath(self.outside.name)
        _git(["init", "-b", "main"], self.repo)
        _git(["config", "user.email", "t@example.com"], self.repo)
        _git(["config", "user.name", "t"], self.repo)

    def tearDown(self):
        self.tmp.cleanup()
        self.outside.cleanup()

    def _run_cmd(self, fn, args):
        buf = StringIO()
        ctxs = [
            patch.dict(os.environ,
                       {"CLAUDE_PROJECT_DIR": self.repo, "HOME": self.elsewhere},
                       clear=True),
            patch.object(handoff, "git_facts", lambda root: dict(FAKE_FACTS)),
            patch.object(handoff, "transcript_hint", lambda root: []),
            patch("sys.stdout", buf),
        ]
        for c in ctxs:
            c.start()
        try:
            rc = fn(args)
        finally:
            for c in reversed(ctxs):
                c.stop()
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def _commit_something(self):
        Path(self.repo, "f.txt").write_text("hi\n")
        _git(["add", "."], self.repo)
        _git(["commit", "-m", "init"], self.repo)

    def _save(self, summary="summary"):
        return self._run_cmd(handoff.cmd_save, _Args(
            summary=summary, done="- did this", next="- to do", verify="tests pass"))

    def _load(self):
        return self._run_cmd(handoff.cmd_load, _Args())

    def _target(self):
        return handoff.handoff_path(self.repo, handoff.current_branch(self.repo))

    def _state(self):
        return handoff.handoff_sync_state(self.repo, self._target())

    def _rel(self):
        return os.path.relpath(self._target(), self.repo).replace(os.sep, "/")

    def _add(self):
        _git(["add", "--", self._rel()], self.repo)

    def _save_add_commit(self):
        self._save()
        self._add()
        _git(["commit", "-m", "handoff"], self.repo)

    def _write_handoff(self, body):
        """Write the file directly, bypassing save (reproduces files left by older versions)."""
        path = self._target()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_text(body, encoding="utf-8")
        return path

    # ---------- state detection boundaries ----------

    def test_missing_file(self):
        self._commit_something()
        self.assertEqual(self._state(), "missing")

    def test_untracked_after_save(self):
        """Right after save — not committed, not even `git add`ed."""
        self._commit_something()
        self._save()
        self.assertEqual(self._state(), "untracked")

    def test_staged_new_is_not_committed(self):
        """A bare `git add` makes it tracked but **not committed**. Looking only at
        ls-files misses that."""
        self._commit_something()
        self._save()
        self._add()
        self.assertEqual(self._state(), "staged-new")

    def test_committed_clean(self):
        self._commit_something()
        self._save_add_commit()
        self.assertEqual(self._state(), "committed-clean")

    def test_committed_then_modified(self):
        """Saving again after a commit — the printed body is no longer the HEAD content."""
        self._commit_something()
        self._save_add_commit()
        self._save(summary="new summary")
        self.assertEqual(self._state(), "committed-modified")

    def test_committed_then_modified_stays_modified_when_staged(self):
        """`git add`ing the modification keeps it 'modified after commit'. Staged does not
        mean it is in HEAD."""
        self._commit_something()
        self._save_add_commit()
        self._save(summary="new summary")
        self._add()
        self.assertEqual(self._state(), "committed-modified")

    def test_assume_unchanged_modification_is_still_modified(self):
        """`assume-unchanged` fools `git diff` — which is why contents are compared directly.

        With diff-based detection this would come out committed-clean, reviving the false
        claim from #133.
        """
        self._commit_something()
        self._save_add_commit()
        _git(["update-index", "--assume-unchanged", "--", self._rel()], self.repo)
        with open(self._target(), "a", encoding="utf-8") as f:
            f.write("\nhand-appended line — not present in HEAD\n")
        # Premise check: diff really does report 'no difference'
        diff = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", self._rel()],
                              cwd=self.repo)
        self.assertEqual(diff.returncode, 0, "premise failed: assume-unchanged had no effect")
        self.assertEqual(self._state(), "committed-modified")

    def test_skip_worktree_modification_is_still_modified(self):
        self._commit_something()
        self._save_add_commit()
        _git(["update-index", "--skip-worktree", "--", self._rel()], self.repo)
        with open(self._target(), "a", encoding="utf-8") as f:
            f.write("\nanother hand edit\n")
        self.assertEqual(self._state(), "committed-modified")

    def test_removed_from_index_after_commit(self):
        """`git rm --cached` — present in HEAD, but the current file is untracked."""
        self._commit_something()
        self._save_add_commit()
        _git(["rm", "--cached", "--", self._rel()], self.repo)
        self.assertEqual(self._state(), "committed-untracked")

    def test_unborn_head_is_not_committed(self):
        """A fresh repository with no commits — a 'HEAD lookup failed' must not be mistaken
        for committed.

        (cmd_save treats an unborn HEAD as DETACHED and refuses, so the file is written
        directly. Files arriving through this path are e.g. saved elsewhere and moved over
        without a commit.)
        """
        path = self._write_handoff("# Handoff\n")
        self.assertEqual(handoff.handoff_sync_state(self.repo, path), "untracked")
        _git(["add", "--", self._rel()], self.repo)
        self.assertEqual(handoff.handoff_sync_state(self.repo, path), "staged-new")

    def test_non_git_directory_is_unknown_not_committed(self):
        """Somewhere that is not a git repository — real git runs here, no mocking, and the
        answer must be unknown."""
        path = os.path.join(self.elsewhere, handoff.HANDOFF_DIR, "x.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_text("# x\n", encoding="utf-8")
        self.assertEqual(handoff.handoff_sync_state(self.elsewhere, path), "unknown")

    def test_git_failure_is_unknown(self):
        """If git itself fails to run, the answer is 'cannot tell' — never committed."""
        self._commit_something()
        self._save()
        with patch.object(handoff, "probe", lambda cmd, cwd=None: (None, False)):
            self.assertEqual(self._state(), "unknown")
        # Case-insensitive: the unknown label must not contain the word at all, in any case.
        self.assertNotIn("committed", handoff.handoff_state_label("unknown").lower())

    def test_abnormal_exit_is_unknown_not_absence(self):
        """A lookup dying with 128 is not 'absent' — it must not be flattened with `!= 0`.

        For a fully committed file whose ls-files exits abnormally, the answer is unknown,
        not untracked.
        """
        self._commit_something()
        self._save_add_commit()
        self.assertEqual(self._state(), "committed-clean")
        real = handoff.probe

        def flaky(cmd, cwd=None):
            return (128, True) if "ls-files" in cmd else real(cmd, cwd=cwd)

        with patch.object(handoff, "probe", flaky):
            self.assertEqual(self._state(), "unknown")

    def test_line_ending_difference_is_reported_modified(self):
        """Calling a file that differs only in line endings `committed-modified` is a
        **deliberate choice**.

        The comparison is byte-for-byte against the HEAD blob, so an autocrlf checkout or a
        clean/smudge filter shows up as modified even when the content matches. Normalizing
        here would make a CRLF-committed blob equal an LF working tree, opening the path to
        calling content that is missing from HEAD clean — which is exactly the direction
        #133 got wrong. Erring toward suspicion is correct.
        """
        self._commit_something()
        self._save_add_commit()
        self.assertEqual(self._state(), "committed-clean")
        data = Path(self._target()).read_bytes()
        Path(self._target()).write_bytes(data.replace(b"\n", b"\r\n"))
        self.assertEqual(self._state(), "committed-modified")

    def test_head_blob_read_failure_is_unknown(self):
        """If the HEAD content cannot be read, claim neither same nor different."""
        self._commit_something()
        self._save_add_commit()
        with patch.object(handoff, "head_blob", lambda root, rel: None):
            self.assertEqual(self._state(), "unknown")

    # ---------- output ----------

    def test_load_labels_uncommitted_states_honestly(self):
        self._commit_something()
        self._save()
        out = self._load()
        self.assertIn("not committed", out)
        # Look at the **whole** output. Reporting 'not committed' up front and then telling
        # the reader to "proceed from the committed handoff" further down, in the deep
        # recovery line, would contradict itself within one output.
        for claim in COMMITTED_CLAIMS:
            self.assertNotIn(claim, out, f"uncommitted handoff labelled '{claim}'")

    def test_load_says_committed_only_when_head_matches(self):
        self._commit_something()
        self._save_add_commit()
        out = self._load()
        self.assertIn(handoff.HANDOFF_STATE_LABELS["committed-clean"], out)
        self.assertIn("pushed state is separate", out,
                      "a local commit must not be claimed as shared with the remote")

        self._save(summary="new summary")
        out2 = self._load()
        self.assertIn("modified after commit", out2)
        self.assertIn("working tree", out2)

    def test_load_does_not_contradict_itself_when_clean(self):
        """Adding 'this is not the committed content' while committed-clean contradicts
        itself.

        The body line must state **provenance** only (the working-tree file was read).
        """
        self._commit_something()
        self._save_add_commit()
        out = self._load()
        self.assertIn("committed — the current file matches the HEAD commit", out)
        self.assertNotIn("not the content committed in HEAD", out)
        self.assertIn("working-tree file as read from disk", out,
                      "provenance still has to be stated")

    def test_legacy_banner_does_not_win_over_real_state(self):
        """Even when an older version's baked-in 'this file is **committed**' banner is
        still in the body, the reader has to see the real state **before** running into
        that sentence."""
        self._commit_something()
        self._write_handoff(
            "# 작업 핸드오프 — main\n\n" + LEGACY_BANNER + "\n\n## 요약\n옛날 파일\n")
        out = self._load()
        self.assertIn(LEGACY_BANNER, out, "the body is shown as-is (never censored)")
        self.assertIn("not committed", out)
        self.assertLess(out.index("not committed"), out.index(LEGACY_BANNER),
                        "the real state has to come before the old version's banner")

    def test_legacy_korean_body_is_reproduced_in_full(self):
        """Old Korean handoff files must still load with their body intact.

        Translating the generated output must not filter, rewrite or drop anything from a
        file written by an earlier version — `load` echoes the working-tree file verbatim,
        and the only thing that changes is the English state header above it.
        """
        self._commit_something()
        legacy = (
            "# 작업 핸드오프 — main\n\n"
            "> 갱신: 2026-01-02T03:04:05+09:00 · 에이전트: codex · 머신: 비공개\n\n"
            "## 요약\n지난 세션에서 훅 경로를 고쳤다\n\n"
            "## 완료한 것\n- routes.json 매핑 추가\n\n"
            "## 남은 것 / 다음 액션\n- 회귀 테스트 작성\n\n"
            "## 검증 상태\n테스트 3개 통과\n"
        )
        self._write_handoff(legacy)
        out = self._load()

        for chunk in ("## 요약", "지난 세션에서 훅 경로를 고쳤다",
                      "## 완료한 것", "- routes.json 매핑 추가",
                      "## 남은 것 / 다음 액션", "- 회귀 테스트 작성",
                      "## 검증 상태", "테스트 3개 통과",
                      "에이전트: codex", "머신: 비공개"):
            self.assertIn(chunk, out, f"legacy body lost: {chunk}")
        self.assertLess(out.index("not committed"), out.index("## 요약"),
                        "the computed state has to precede the legacy body")

    def test_load_missing_file_does_not_claim_commit(self):
        self._commit_something()
        out = self._load()
        self.assertIn("Handoff file: none", out)
        for claim in COMMITTED_CLAIMS:
            self.assertNotIn(claim, out)

    def test_saved_body_has_no_commit_status_claim(self):
        """The body must not be false on either side of a commit — no state is baked in.

        The claim is matched **after stripping Markdown emphasis**. The original #133 bug
        shipped as `이 파일은 **커밋됨**`, and its most direct English form is
        `This file is **committed**` — a plain substring check for "this file is committed"
        walks straight past both, because the asterisks sit between the words.

        Instructions stay legal: "it has to be committed and pushed", "check git for the
        real state". Those remain true on both sides of a commit; a status assertion does
        not.
        """
        self._commit_something()
        self._save()
        body = Path(self._target()).read_text(encoding="utf-8")

        # The exact historical claim, verbatim and unnormalized — this is the string the
        # original test rejected, and it must keep being rejected.
        self.assertNotIn("이 파일은 **커밋됨**", body)

        flat = _strip_emphasis(body)
        for claim in FORBIDDEN_STATUS_CLAIMS:
            self.assertNotIn(claim, flat,
                             f"the saved body asserts a commit state: {claim!r}")
        for label in COMMITTED_LABELS:
            self.assertNotIn(_strip_emphasis(label), flat)

        self.assertIn("check git, not this body", flat,
                      "the body must still point the reader at git for the real state")
        self.assertIn("committed and pushed", flat,
                      "the instruction to commit and push must stay — it is not a status claim")

    def test_saved_body_has_no_absolute_path(self):
        """The body is the portable source of truth across machines — no absolute paths
        from this machine."""
        self._commit_something()
        self._save()
        self.assertNotIn(self.repo, Path(self._target()).read_text(encoding="utf-8"))

    def test_saved_body_keeps_narrative_sections(self):
        """Fixing the state banner must not lose the sections a human wrote."""
        self._commit_something()
        self._save(summary="this summary")
        body = Path(self._target()).read_text(encoding="utf-8")
        for chunk in ("## Summary", "this summary", "## Done", "- did this",
                      "## Remaining / next actions", "- to do",
                      "## Verification status", "tests pass"):
            self.assertIn(chunk, body)

    def test_save_prints_command_that_runs_from_any_cwd(self):
        """The printed command must work on the target repository even when pasted **from a
        cwd outside the repo**.

        cwd ≠ target repository is the normal path with `--project-dir` or a Codex
        skill-folder run. This also checks that quoting survives a branch name containing
        shell metacharacters.
        """
        self._commit_something()
        _git(["checkout", "-b", "fix/it's-$weird"], self.repo)
        lines = self._save().splitlines()

        add = shlex.split(next(l for l in lines if " add -- " in l).strip())
        self.assertEqual(add[:5], ["git", "-C", self.repo, "add", "--"])
        self.assertEqual(add[5], self._rel())

        # Check it actually works — run it from outside the repo (broken quoting or a
        # missing -C dies right here)
        done = subprocess.run(add, cwd=self.elsewhere, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self._state(), "staged-new")

        # Match on the printed command itself, not on the word "commit" — the state line
        # above it ("not committed — …") contains that word too.
        commit = next(l.strip() for l in lines
                      if l.strip().startswith("git -C") and " commit" in l)
        self.assertEqual(shlex.split(commit.split("#")[0])[:4],
                         ["git", "-C", self.repo, "commit"])

    def test_save_reports_current_state(self):
        self._commit_something()
        self.assertIn("Current git state: not committed", self._save())


if __name__ == "__main__":
    unittest.main()
