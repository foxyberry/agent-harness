import builtins
import importlib.util
import pathlib
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "core" / "hooks" / "pr-merge-reflect.py"
SPEC = importlib.util.spec_from_file_location("pr_merge_reflect", SCRIPT)
pr_merge_reflect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pr_merge_reflect)


class PrMergeReflectTest(unittest.TestCase):
    def test_corrupt_state_is_reseeded_instead_of_replaying_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = pathlib.Path(tmp) / "state.json"
            cache.write_text('{"seen":')

            with patch.object(
                pr_merge_reflect,
                "_recent_merged",
                return_value=[(3, "three"), (2, "two"), (1, "one")],
            ), patch.object(pr_merge_reflect, "_should_skip_reflect") as should_skip, \
                    patch.object(pr_merge_reflect, "_announce_pending_drafts"), \
                    patch.object(pr_merge_reflect, "_sweep_codex_sessions"):
                pr_merge_reflect._on_session_start(tmp, str(cache))

            should_skip.assert_not_called()
            state = pr_merge_reflect._load_state(str(cache))
            self.assertEqual(state, {"seen": {1, 2, 3}, "pending": []})

    def test_valid_json_with_invalid_state_shape_is_reseeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = pathlib.Path(tmp) / "state.json"
            cache.write_text('{"seen":[1],"pending":[{"number":2}]}')

            self.assertIsNone(pr_merge_reflect._load_state(str(cache)))

    def test_transient_read_error_does_not_trigger_reseed_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = pathlib.Path(tmp) / "state.json"
            cache.write_text('{"seen":[1],"pending":[]}')

            with patch("builtins.open", side_effect=OSError("temporary")), \
                    patch.object(pr_merge_reflect, "_save_state") as save_state, \
                    patch.object(pr_merge_reflect, "_recent_merged", return_value=[(2, "two")]), \
                    patch.object(pr_merge_reflect, "_announce_pending_drafts") as announce, \
                    patch.object(pr_merge_reflect, "_sweep_codex_sessions") as sweep:
                pr_merge_reflect._on_session_start(tmp, str(cache))

            save_state.assert_not_called()
            announce.assert_called_once_with(tmp)
            sweep.assert_called_once_with(tmp)

    def test_post_tool_does_not_turn_corrupt_cache_into_empty_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = pathlib.Path(tmp) / "state.json"
            cache.write_text('{"seen":')
            data = {
                "tool_name": "Bash",
                "tool_input": {"command": "gh pr merge 42 --squash"},
            }

            with patch.object(pr_merge_reflect, "_pr_is_merged", return_value=True), \
                    patch.object(pr_merge_reflect, "_should_skip_reflect", return_value=False), \
                    patch.object(pr_merge_reflect, "_spawn_reflect_job"):
                pr_merge_reflect._on_post_tool(data, tmp, str(cache))

            self.assertEqual(cache.read_text(), '{"seen":')

            with patch.object(
                pr_merge_reflect,
                "_recent_merged",
                return_value=[(42, "latest"), (41, "older")],
            ), patch.object(pr_merge_reflect, "_should_skip_reflect") as should_skip, \
                    patch.object(pr_merge_reflect, "_announce_pending_drafts"), \
                    patch.object(pr_merge_reflect, "_sweep_codex_sessions"):
                pr_merge_reflect._on_session_start(tmp, str(cache))

            should_skip.assert_not_called()
            self.assertEqual(
                pr_merge_reflect._load_state(str(cache)),
                {"seen": {41, 42}, "pending": []},
            )

    def test_pr_scan_is_capped_and_persisted_incrementally(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = pathlib.Path(tmp) / "state.json"
            pr_merge_reflect._save_state(str(cache), set(), [])
            calls = []

            def record(_project_dir, num):
                calls.append(num)
                return num == 5

            with patch.object(pr_merge_reflect, "_should_skip_reflect", side_effect=record):
                seen, pending = pr_merge_reflect._scan_reflectable(
                    tmp, [5, 4, 3, 2, 1], str(cache), set(), []
                )

            self.assertEqual(calls, [5, 4, 3])
            self.assertEqual(seen, {3, 4, 5})
            self.assertEqual(pending, [4, 3])
            self.assertEqual(
                pr_merge_reflect._load_state(str(cache)),
                {"seen": {3, 4, 5}, "pending": [4, 3]},
            )

    def test_atomic_write_leaves_valid_json_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = pathlib.Path(tmp) / "state.json"
            pr_merge_reflect._save_state(str(cache), {1}, [1])

            with patch.object(pr_merge_reflect.os, "replace", side_effect=OSError("stop")):
                pr_merge_reflect._save_state(str(cache), {2}, [2])

            self.assertEqual(
                pr_merge_reflect._load_state(str(cache)),
                {"seen": {1}, "pending": [1]},
            )
            self.assertEqual(list(pathlib.Path(tmp).glob(".tmp-*.json")), [])

    def test_corrupt_codex_seen_cache_seeds_without_reflecting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project = root / "project"
            project.mkdir()
            rollout = root / ".codex" / "sessions" / "2026" / "08" / "19" / "rollout-test.jsonl"
            rollout.parent.mkdir(parents=True)
            rollout.write_text(
                '{"type":"session_meta","payload":{"id":"session-1","cwd":"'
                + str(project)
                + '"}}\n'
            )
            old = time.time() - 3600
            pr_merge_reflect.os.utime(rollout, (old, old))
            seen_path = project / ".claude" / ".cache" / "codex-reflect-seen.json"
            seen_path.parent.mkdir(parents=True)
            seen_path.write_text("[")

            class Matcher:
                def __init__(self, _project_dir):
                    pass

                def record_worktrees(self):
                    pass

                def belongs(self, cwd):
                    return cwd == str(project)

            with patch.dict(
                pr_merge_reflect.os.environ,
                {"HOME": str(root), "HARNESS_AUTO_REFLECT": "1"},
            ), patch.object(pr_merge_reflect, "ProjectMatcher", Matcher), \
                    patch.object(pr_merge_reflect, "_run_reflect") as run_reflect:
                pr_merge_reflect._sweep_codex_sessions(str(project))

            run_reflect.assert_not_called()
            self.assertEqual(
                pr_merge_reflect.json.loads(seen_path.read_text()), ["session-1"]
            )

    def test_cache_exclude_is_added_once_without_tracked_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            exclude = pathlib.Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "info/exclude"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            )
            if not exclude.is_absolute():
                exclude = root / exclude
            exclude.write_text("# keep existing rule")

            pr_merge_reflect._ensure_local_cache_exclude(str(root))
            pr_merge_reflect._ensure_local_cache_exclude(str(root))

            lines = exclude.read_text().splitlines()
            self.assertIn("# keep existing rule", lines)
            self.assertEqual(lines.count(".claude/.cache/"), 1)
            self.assertFalse((root / ".gitignore").exists())
            ignored = subprocess.run(
                ["git", "check-ignore", ".claude/.cache/reflect.log"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(ignored.returncode, 0)

    def test_linked_worktree_uses_git_resolved_exclude(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            root = base / "root"
            worktree = base / "worktree"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=root, check=True
            )
            (root / "tracked.txt").write_text("tracked\n")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "initial"], cwd=root, check=True
            )
            subprocess.run(
                ["git", "worktree", "add", "-q", str(worktree), "-b", "feature"],
                cwd=root,
                check=True,
            )

            pr_merge_reflect._ensure_local_cache_exclude(str(worktree))

            ignored = subprocess.run(
                ["git", "check-ignore", ".claude/.cache/reflect.log"],
                cwd=worktree,
                capture_output=True,
                text=True,
            )
            self.assertEqual(ignored.returncode, 0)

    def test_monorepo_subdirectory_uses_repo_relative_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project = root / "packages" / "api"
            project.mkdir(parents=True)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)

            pr_merge_reflect._ensure_local_cache_exclude(str(project))

            ignored = subprocess.run(
                ["git", "check-ignore", "packages/api/.claude/.cache/reflect.log"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(ignored.returncode, 0)
            exclude = root / ".git" / "info" / "exclude"
            self.assertIn("packages/api/.claude/.cache/", exclude.read_text().splitlines())

    def test_non_git_project_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            pr_merge_reflect._ensure_local_cache_exclude(tmp)
            self.assertEqual(list(pathlib.Path(tmp).iterdir()), [])

    def test_permission_error_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            exclude = root / ".git" / "info" / "exclude"
            before = exclude.read_text()
            real_open = builtins.open

            def deny_exclude(path, *args, **kwargs):
                if str(path).endswith("info/exclude"):
                    raise PermissionError("read-only")
                return real_open(path, *args, **kwargs)

            with patch("builtins.open", side_effect=deny_exclude):
                pr_merge_reflect._ensure_local_cache_exclude(str(root))
            self.assertEqual(exclude.read_text(), before)
