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


class ProjectTemplateTest(unittest.TestCase):
    def test_pr_template_and_check_require_bilingual_implementation_logic(self):
        template = (TEMPLATE / ".github" / "pull_request_template.md").read_text()
        workflow = (
            TEMPLATE / ".github" / "workflows" / "pr-body-check.yml"
        ).read_text()
        agents = (TEMPLATE / "AGENTS.md").read_text()
        sections = [
            "## 구현 내용 (KR)",
            "## 구현 로직 (KR)",
            "## Implementation Summary (EN)",
            "## Implementation Logic (EN)",
        ]

        for section in sections:
            self.assertIn(section, template)
            self.assertIn(section.removeprefix("## "), workflow)
            self.assertIn(section.removeprefix("## "), agents)
        self.assertIn("feat|fix|refactor|perf", workflow)
        self.assertIn("length < 20", workflow)
        self.assertIn("파일 이름", agents)

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
        valid_body = """## 구현 내용 (KR)
사용자가 저장 버튼을 누르면 초안을 서버에 저장합니다.
## 구현 로직 (KR)
입력값을 검증한 뒤 저장하고, 실패하면 기존 초안을 유지합니다.
## Implementation Summary (EN)
Save the user's draft through the API when requested.
## Implementation Logic (EN)
Validate input, persist the draft, and preserve existing data on failure.
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

            self.assertIsNone(check("feat(save): 초안 저장", valid_body))
            self.assertIsNone(check("docs(readme): 설치 안내", ""))
            self.assertIsNone(check('Revert "feat(save): 초안 저장"', ""))
            self.assertIsNone(check('Revert "Revert \\"feat(save): 초안 저장\\""', ""))
            self.assertIsNone(
                check("feat(save): 초안 저장", "", [{"name": "skip-pr-body-check"}])
            )
            self.assertIn("Missing or too short", check("fix(save): 저장 복구"))
            for title in (
                "[feature/issue1] feat: 저장",
                "✨ feat(save): 저장",
                "feat (save): 저장",
            ):
                self.assertIn("PR titles must start", check(title))
            self.assertIn(
                "PR titles must start",
                check(
                    "[feature/issue1] feat: 저장",
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
            review_ledger = (
                project / ".claude" / ".cache" / "review-ledger" / "pr-123.json"
            )
            root_cache = project / ".cache" / "keep.txt"
            source_cache = project / "src" / ".cache" / "keep.txt"
            pending_decision.parent.mkdir(parents=True, exist_ok=True)
            review_ledger.parent.mkdir(parents=True, exist_ok=True)
            root_cache.parent.mkdir(parents=True, exist_ok=True)
            source_cache.parent.mkdir(parents=True, exist_ok=True)
            pending.write_text("unreviewed\n")
            pending_decision.write_text("unreviewed decision\n")
            approved.write_text("approved\n")
            decision.write_text("approved decision\n")
            reflect_log.write_text("local reflection output\n")
            review_ledger.write_text("{}\n")
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
            self.assertNotIn(".claude/.cache/review-ledger/pr-123.json", status)
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
