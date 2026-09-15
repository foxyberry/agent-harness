import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "project-template"

EN_SECTIONS = [
    "## Implementation Summary (EN)",
    "## Implementation Logic (EN)",
]
KOREAN_SUMMARY = "사용자가 저장 버튼을 누르면 초안을 서버에 저장합니다."
KOREAN_LOGIC = "입력값을 검증한 뒤 저장하고, 실패하면 기존 초안을 유지합니다."
EN_SUMMARY = "Save the user's draft through the API when requested."
EN_LOGIC = "Validate input, persist the draft, and preserve existing data on failure."


class ProjectTemplateTest(unittest.TestCase):
    def test_pr_template_and_check_require_english_implementation_logic(self):
        template = (TEMPLATE / ".github" / "pull_request_template.md").read_text()
        workflow = (
            TEMPLATE / ".github" / "workflows" / "pr-body-check.yml"
        ).read_text()
        agents = (TEMPLATE / "AGENTS.md").read_text()

        for section in EN_SECTIONS:
            self.assertIn(section, template)
            self.assertIn(section.removeprefix("## "), workflow)
            self.assertIn(section.removeprefix("## "), agents)

        # Korean is supplementary: the shipped template offers the optional section under an
        # English heading, and the rules say English is required with Korean as an extra.
        self.assertIn("## Korean notes (optional)", template)
        self.assertIn("Korean notes (optional)", agents)
        self.assertIn("in English", agents)
        # The validator must not gate on any Korean heading, however the regex is spelled.
        self.assertNotIn("구현", workflow)

        self.assertIn("feat|fix|refactor|perf", workflow)
        self.assertIn("length < 20", workflow)
        self.assertIn("file names", agents)

    @unittest.skipUnless(shutil.which("node"), "node is required")
    def test_pr_body_check_behavior(self):
        workflow = (
            TEMPLATE / ".github" / "workflows" / "pr-body-check.yml"
        ).read_text()
        script = textwrap.dedent(workflow.split("          script: |\n", 1)[1])
        runner = """
const pr = JSON.parse(process.argv[2]);
let failure = null;
const context = { payload: { pull_request: pr } };
const core = {
  info: () => {},
  setFailed: (message) => { failure = String(message); },
};
(async () => {
%s
})().then(() => console.log(JSON.stringify({ failure })));
""" % textwrap.indent(script, "  ")

        english_only = f"""## Implementation Summary (EN)
{EN_SUMMARY}
## Implementation Logic (EN)
{EN_LOGIC}
"""
        english_with_korean_note = f"""{english_only}## 구현 노트 (KR)
{KOREAN_SUMMARY}
"""
        # The previous policy required four bilingual sections. Bodies written that way must
        # keep passing — the new rule is strictly more permissive.
        legacy_bilingual = f"""## 구현 내용 (KR)
{KOREAN_SUMMARY}
## 구현 로직 (KR)
{KOREAN_LOGIC}
{english_only}"""
        korean_only = f"""## 구현 내용 (KR)
{KOREAN_SUMMARY}
## 구현 로직 (KR)
{KOREAN_LOGIC}
"""
        missing_summary = f"""## Implementation Logic (EN)
{EN_LOGIC}
"""
        missing_logic = f"""## Implementation Summary (EN)
{EN_SUMMARY}
"""
        short_summary = f"""## Implementation Summary (EN)
Saves it.
## Implementation Logic (EN)
{EN_LOGIC}
"""
        short_logic = f"""## Implementation Summary (EN)
{EN_SUMMARY}
## Implementation Logic (EN)
Validates.
"""
        placeholder_only = """## Implementation Summary (EN)
<!-- Required. Summarize what was implemented in clear English. -->
## Implementation Logic (EN)
<!-- Required. Explain the core execution flow in English. -->
"""

        with tempfile.TemporaryDirectory() as tmp:
            runner_path = pathlib.Path(tmp) / "pr-body-check.js"
            runner_path.write_text(runner)

            def check(title, body="", labels=None):
                result = subprocess.run(
                    [
                        "node",
                        str(runner_path),
                        json.dumps(
                            {"title": title, "body": body, "labels": labels or []},
                            ensure_ascii=False,
                        ),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return json.loads(result.stdout)["failure"]

            # English alone is enough; Korean is accepted but never required.
            self.assertIsNone(check("feat(save): save draft", english_only))
            self.assertIsNone(
                check("feat(save): save draft", english_with_korean_note)
            )
            # A Korean title still passes the language-agnostic title gate.
            self.assertIsNone(check("feat(save): 초안 저장", legacy_bilingual))

            # Either English section missing, too short, or replaced by Korean fails.
            for body, expected in (
                (korean_only, ["Implementation Summary (EN)", "Implementation Logic (EN)"]),
                (missing_summary, ["Implementation Summary (EN)"]),
                (missing_logic, ["Implementation Logic (EN)"]),
                (short_summary, ["Implementation Summary (EN)"]),
                (short_logic, ["Implementation Logic (EN)"]),
                (placeholder_only, ["Implementation Summary (EN)", "Implementation Logic (EN)"]),
                ("", ["Implementation Summary (EN)", "Implementation Logic (EN)"]),
            ):
                with self.subTest(body=body[:40]):
                    failure = check("fix(save): restore saving", body)
                    self.assertIn("Missing or too short", failure)
                    for name in expected:
                        self.assertIn(name, failure)
                    for name in EN_SECTIONS:
                        if name.removeprefix("## ") not in expected:
                            self.assertNotIn(name.removeprefix("## "), failure)

            # Non-implementation types, GitHub reverts and skip labels keep their behavior.
            self.assertIsNone(check("docs(readme): install guide", ""))
            self.assertIsNone(check('Revert "feat(save): 초안 저장"', ""))
            self.assertIsNone(check('Revert "Revert \\"feat(save): 초안 저장\\""', ""))
            self.assertIsNone(
                check("feat(save): save draft", "", [{"name": "skip-pr-body-check"}])
            )
            for title in (
                "[feature/issue1] feat: save",
                "✨ feat(save): save",
                "feat (save): save",
            ):
                self.assertIn("PR titles must start", check(title))
            # The title gate runs before the skip label.
            self.assertIn(
                "PR titles must start",
                check(
                    "[feature/issue1] feat: save",
                    "",
                    [{"name": "skip-pr-body-check"}],
                ),
            )

    def test_runtime_files_are_ignored_but_approved_memory_is_trackable(self):
        self.assertFalse((TEMPLATE / ".gitignore").exists())

        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp)
            shutil.copytree(TEMPLATE, project, dirs_exist_ok=True)
            git_env = os.environ.copy()
            git_env["GIT_CONFIG_GLOBAL"] = os.devnull
            git_env["GIT_CONFIG_NOSYSTEM"] = "1"
            git_env["XDG_CONFIG_HOME"] = str(project / ".xdg-config")
            subprocess.run(
                ["git", "init", "-q"], cwd=project, check=True, env=git_env
            )

            pending = project / ".claude" / "memory" / "_pending" / "draft.md"
            pending_decision = (
                project
                / ".claude"
                / "memory"
                / "_pending"
                / "decisions"
                / "draft.md"
            )
            approved = project / ".claude" / "memory" / "approved.md"
            decision = project / ".claude" / "memory" / "decisions" / "approved.md"
            reflect_log = project / ".claude" / ".cache" / "reflect.log"
            nested_cache = (
                project / ".claude" / ".cache" / "agent-tool" / "scratch.json"
            )
            root_cache = project / ".cache" / "keep.txt"
            source_cache = project / "src" / ".cache" / "keep.txt"
            pending_decision.parent.mkdir(parents=True, exist_ok=True)
            nested_cache.parent.mkdir(parents=True, exist_ok=True)
            root_cache.parent.mkdir(parents=True, exist_ok=True)
            source_cache.parent.mkdir(parents=True, exist_ok=True)
            pending.write_text("unreviewed\n")
            pending_decision.write_text("unreviewed decision\n")
            approved.write_text("approved\n")
            decision.write_text("approved decision\n")
            reflect_log.write_text("local reflection output\n")
            root_cache.write_text("project cache\n")
            source_cache.write_text("source cache\n")

            status = subprocess.run(
                ["git", "status", "--short", "--untracked-files=all"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
                env=git_env,
            ).stdout
            status_paths = {
                line[3:] for line in status.splitlines() if len(line) >= 4
            }
            ignored_by = subprocess.run(
                ["git", "check-ignore", "-v", str(pending.relative_to(project))],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
                env=git_env,
            ).stdout
            cache_ignored_by = subprocess.run(
                [
                    "git",
                    "check-ignore",
                    "-v",
                    str(reflect_log.relative_to(project)),
                ],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
                env=git_env,
            ).stdout

            self.assertNotIn("_pending/draft.md", status)
            self.assertNotIn("_pending/decisions/draft.md", status)
            self.assertNotIn(".claude/.cache/reflect.log", status)
            self.assertNotIn(".claude/.cache/agent-tool/scratch.json", status)
            self.assertIn(".cache/keep.txt", status_paths)
            self.assertIn("src/.cache/keep.txt", status_paths)
            self.assertIn(".claude/memory/approved.md", status)
            self.assertIn(".claude/memory/decisions/approved.md", status)
            self.assertIn(".claude/.gitignore", status)
            self.assertIn(".claude/memory/.gitignore", status)
            memory_source, _, memory_pattern = ignored_by.split("\t", 1)[0].rsplit(
                ":", 2
            )
            cache_source, _, cache_pattern = cache_ignored_by.split("\t", 1)[
                0
            ].rsplit(":", 2)
            self.assertEqual(memory_source, ".claude/memory/.gitignore")
            self.assertEqual(memory_pattern, "_pending/")
            self.assertEqual(cache_source, ".claude/.gitignore")
            self.assertEqual(cache_pattern, ".cache/")
