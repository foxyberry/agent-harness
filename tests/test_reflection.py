import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "core" / "hooks" / "reflection.py"
CONFIG = ROOT / "project-template" / ".claude" / "memory" / "reflection-rules.json"
SPEC = importlib.util.spec_from_file_location("reflection", SCRIPT)
reflection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reflection)


class PackLoadingTest(unittest.TestCase):
    def test_disabled_pack_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "reflection-rules.json").write_text(
                json.dumps(
                    {
                        "rules": [{"regex": "base", "message": "base"}],
                        "packs": [
                            {
                                "name": "optional",
                                "enabled": False,
                                "rules": [{"regex": "pack", "message": "pack"}],
                            }
                        ],
                    }
                )
            )

            config = reflection._load_config(tmp)

        self.assertEqual(["base"], [rule["regex"] for rule in config["rules"]])

    def test_enabled_pack_rules_are_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "reflection-rules.json").write_text(
                json.dumps(
                    {
                        "rules": [{"regex": "base", "message": "base"}],
                        "packs": [
                            {
                                "name": "optional",
                                "enabled": True,
                                "rules": [{"regex": "pack", "message": "pack"}],
                            }
                        ],
                    }
                )
            )

            config = reflection._load_config(tmp)

        self.assertEqual(
            ["base", "pack"], [rule["regex"] for rule in config["rules"]]
        )

    def test_disabled_rule_is_ignored(self):
        warning = reflection._apply_rule(
            {"enabled": False, "regex": "TODO", "message": "disabled"},
            "src/example.ts",
            "// TODO",
        )
        self.assertIsNone(warning)

    def test_globs_match_only_listed_extensions(self):
        rule = {
            "globs": ["*.js", "*.jsx", "*.ts", "*.tsx"],
            "regex": "catch",
            "message": "candidate",
        }
        self.assertIsNotNone(
            reflection._apply_rule(rule, "src/useProgress.ts", "catch")
        )
        self.assertIsNone(
            reflection._apply_rule(rule, "fixtures/package.json", "catch")
        )


class ReactTimingPackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads(CONFIG.read_text())
        cls.pack = next(pack for pack in data["packs"] if pack["name"] == "react-async-timing")
        cls.rules = cls.pack["rules"]

    def test_pack_is_opt_in(self):
        self.assertIs(self.pack["enabled"], False)

    def assert_rule_matches(self, index, content):
        warning = reflection._apply_rule(self.rules[index], "src/hook.tsx", content)
        self.assertIsNotNone(warning)

    def assert_rule_does_not_match(self, index, content):
        warning = reflection._apply_rule(self.rules[index], "src/hook.tsx", content)
        self.assertIsNone(warning)

    def test_updater_side_effect_candidate(self):
        self.assert_rule_matches(
            0,
            "setWords((prev: Set<string>) => localStorage.setItem('words', '[]'));",
        )

    def test_updater_does_not_cross_function_boundary(self):
        self.assert_rule_does_not_match(
            0,
            "setWords(prev => prev); function save() { localStorage.setItem('x', '1'); }",
        )

    def test_catch_without_completion_signal_candidate(self):
        self.assert_rule_matches(
            1,
            "try { await load(); } catch (error) { report(error); }",
        )

    def test_catch_with_completion_signal_is_not_flagged(self):
        self.assert_rule_does_not_match(
            1,
            "try { await load(); } catch (error) { report(error); setIsLoaded(true); }",
        )

    def test_completion_signal_after_catch_does_not_hide_candidate(self):
        self.assert_rule_matches(
            1,
            "try { await load(); } catch (error) { report(error); } setLoaded(true);",
        )

    def test_typescript_hook_file_is_included(self):
        warning = reflection._apply_rule(
            self.rules[1],
            "src/useProgress.ts",
            "try { await load(); } catch (error) { report(error); }",
        )
        self.assertIsNotNone(warning)

    def test_ref_render_branch_candidate(self):
        self.assert_rule_matches(2, "const canSave = loadedRef.current === true;")

    def test_effect_initial_reset_candidate(self):
        self.assert_rule_matches(
            3,
            "useEffect(() => { setCompleted(new Set<string>()); }, [accountId]);",
        )

    def test_enabled_pack_reaches_post_tool_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = Path(tmp, ".claude", "memory")
            memory.mkdir(parents=True)
            data = json.loads(CONFIG.read_text())
            data["packs"][0]["enabled"] = True
            Path(memory, "reflection-rules.json").write_text(json.dumps(data))
            payload = {
                "tool_input": {
                    "file_path": "src/useProgress.tsx",
                    "new_string": (
                        "setWords(prev => { "
                        "localStorage.setItem('words', '[]'); return prev; });"
                    ),
                }
            }

            result = subprocess.run(
                ["python3", str(SCRIPT)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env={**os.environ, "CLAUDE_PROJECT_DIR": tmp},
                check=True,
            )

        output = json.loads(result.stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("state updater 안 부수효과 후보", context)
        self.assertIn("renderHook + rerender", context)


if __name__ == "__main__":
    unittest.main()
