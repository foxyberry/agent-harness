"""Run installed-style hook commands across the queue lifecycle, outside the source tree."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MergeReminderDeliveryTest(unittest.TestCase):
    def test_queue_lifecycle_in_both_bundles(self):
        for adapter, opt_in in (("harness", "0"), ("codex", "0"), ("codex", "1")):
            with self.subTest(adapter=adapter, opt_in=opt_in), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                bundle = root / "bundle"
                shutil.copytree(ROOT / "plugins" / adapter / "hooks", bundle / "hooks")
                project = root / "project"
                (project / ".claude/memory").mkdir(parents=True)
                subprocess.run(["git", "init", "-q", str(project)], check=True)
                bindir = root / "bin"
                bindir.mkdir()
                gh = bindir / "gh"
                gh.write_text("#!/usr/bin/env python3\n"
                              "import json, pathlib, sys\n"
                              "a=sys.argv[1:]\n"
                              "if a[:2]==['pr','list']: print(pathlib.Path('merged.json').read_text())\n"
                              "elif 'state' in a: print('MERGED')\n"
                              "else: print(json.dumps({'files':[{'path':'src/main.py'}], 'labels':[], 'commits':[]}))\n")
                gh.chmod(0o755)
                env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
                       "CLAUDE_PLUGIN_ROOT": str(bundle), "HARNESS_AUTO_REFLECT": opt_in,
                       "CODEX_HOME": str(root / "codex-home")}
                for key in ("CLAUDE_PROJECT_DIR", "REFLECT_JOB", "HARNESS_HOOK_TRACE"):
                    env.pop(key, None)
                config = json.loads((bundle / "hooks/hooks.json").read_text())["hooks"]
                cache = project / ".claude/.cache/pr-merge-seen.json"
                transcript = root / "transcript.jsonl"
                transcript.write_text(json.dumps({"type": "session_meta", "payload": {
                    "id": "current", "cwd": str(project), "originator": "codex-tui", "source": "cli"
                }}) + "\n")

                def run(event, **extra):
                    commands = [h["command"] for group in config[event] for h in group["hooks"]
                                if "pr-merge-reflect.py" in h["command"]]
                    self.assertEqual(len(commands), 1)
                    result = subprocess.run(commands[0], shell=True, cwd=project, env=env,
                                            input=json.dumps({"hook_event_name": event,
                                                              "cwd": str(project),
                                                              "transcript_path": str(transcript), **extra}),
                                            text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    return result.stdout

                (project / "merged.json").write_text('[{"number": 1, "title": "old"}]')
                self.assertEqual(run("SessionStart"), "")
                self.assertEqual(json.loads(cache.read_text())["pending"], [])
                # A confirmed shell merge queues; the next prompt delivers once.
                run("PostToolUse", tool_name="Bash", tool_input={"command": "gh pr merge 2 --squash"})
                self.assertEqual(json.loads(cache.read_text())["pending"], [2])
                payload = json.loads(run("UserPromptSubmit", prompt="Next task"))
                self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
                self.assertIn("#2", payload["hookSpecificOutput"]["additionalContext"])
                self.assertEqual(json.loads(cache.read_text())["pending"], [])
                self.assertEqual(run("UserPromptSubmit", prompt="Next task"), "")
                # A merge from elsewhere is picked up at the next session start.
                (project / "merged.json").write_text('[{"number": 3, "title": "external"}]')
                self.assertEqual(run("SessionStart"), "")
                self.assertEqual(json.loads(cache.read_text())["pending"], [3])
                self.assertIn("#3", run("UserPromptSubmit", prompt="Next task"))
                self.assertEqual(run("UserPromptSubmit", prompt="Next task"), "")
                self.assertFalse((project / ".claude/.cache/reflect.log").exists())
