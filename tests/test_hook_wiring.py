"""Catches **silent failures** in the hook wiring (issue #85, step 4, the in-repo part).

A silent failure is a hook that never ran while nothing visible happened, so nobody
notices. A path typo, a helper that was not copied and a matcher mismatch all land here —
all three look like "quietly succeeded" on screen.

What this catches (all of it deterministically checkable inside this repository):

1. Does the script hooks.json points at actually exist in that bundle? (path typo)
2. Does a registered hook **run from its bundle directory** and exit 0? (missing helper cp
   → death at import)
3. Does the matcher cover the tool names that tool really emits? (matcher mismatch)
4. Do the edit fixtures line up with the edit-hook matchers? (hook_io ↔ hooks.json coupling)

**What this cannot catch**: hooks skipped because the installation is untrusted, and
whether the real tool actually fires them. Both are install state and runtime, invisible to
this repository's tests. Those are observed in a separate project with
`HARNESS_HOOK_TRACE` — the procedure is in docs/codex-hooks.md.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "scripts"))
from hook_io import edited_files  # noqa: E402

# **Inventory of tool names**, per adapter.
#
# ⚠️ This list must not be derived from the matchers — that would be circular, checking
# itself, and would catch nothing. The source is measurement:
#   - Claude: Edit/Write/MultiEdit/Bash (the edit and shell tools this harness uses)
#   - Codex: apply_patch/Bash — measured on codex-cli 0.145.0 in the body of issue #85.
#     The `exec` in rollout logs was a tool_use_id prefix, not a tool name.
ADAPTERS = {
    "harness": {"edit": ["Edit", "Write", "MultiEdit"], "shell": ["Bash"]},
    "codex": {"edit": ["apply_patch"], "shell": ["Bash"]},
}

# The edit hooks. memory-search must fire on the shell too (issue #90); reflection only
# looks at edits.
MEMORY_SEARCH = "memory-search.py"
REFLECTION = "reflection.py"

BUILD_HINT = ("hooks.json is out of sync with the source — run `./build.sh` and commit the "
              "generated output too.")

_COMMAND_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"']+)")


def _hooks_json(adapter):
    path = ROOT / "plugins" / adapter / "hooks" / "hooks.json"
    if not path.exists():
        raise unittest.SkipTest(f"{path} is missing — {BUILD_HINT}")
    return json.loads(path.read_text(encoding="utf-8"))["hooks"]


def _registrations(adapter):
    """[(event, matcher, script_rel_path)] — flattens the registered hooks."""
    out = []
    for event, entries in _hooks_json(adapter).items():
        for entry in entries:
            matcher = entry.get("matcher") or ""
            for hook in entry.get("hooks", []):
                found = _COMMAND_RE.search(hook.get("command", ""))
                assert found, (f"{adapter}/{event}: not a ${{CLAUDE_PLUGIN_ROOT}}-relative path")
                out.append((event, matcher, found.group(1)))
    return out


def _command_registrations(adapter):
    """[(event, matcher, command)] — including the command string that gets executed."""
    out = []
    for event, entries in _hooks_json(adapter).items():
        for entry in entries:
            matcher = entry.get("matcher") or ""
            for hook in entry.get("hooks", []):
                out.append((event, matcher, hook["command"]))
    return out


def _matches(matcher, tool_name):
    """Common to Codex and Claude: a matcher is a regex over the tool name; empty matches everything."""
    if matcher in ("", "*"):
        return True
    return re.search(matcher, tool_name) is not None


class RegisteredPathsTest(unittest.TestCase):
    """1. Path typos — if hooks.json points at a missing file, the hook never runs."""

    def test_every_registered_script_exists_in_its_bundle(self):
        for adapter in ADAPTERS:
            bundle = ROOT / "plugins" / adapter
            for event, _matcher, rel in _registrations(adapter):
                with self.subTest(adapter=adapter, event=event, script=rel):
                    self.assertTrue((bundle / rel).is_file(),
                                    f"{adapter}: {rel} is not in the bundle. {BUILD_HINT}")

    def test_codex_merge_hook_cannot_spawn_reflection_job(self):
        """Phase 3a ships detect-and-queue only. Bundling reflect.py would open duplicated retrospectives during a live rollout."""
        hooks = ROOT / "plugins" / "codex" / "hooks"
        self.assertTrue((hooks / "pr-merge-reflect.py").is_file())
        self.assertFalse((hooks / "reflect.py").exists())

    def test_codex_merge_hook_phase_3a_registration_boundary(self):
        regs = [r for r in _registrations("codex") if r[2].endswith("pr-merge-reflect.py")]
        self.assertEqual(
            [("PostToolUse", "Bash"), ("SessionStart", "")],
            [(event, matcher) for event, matcher, _script in regs],
        )


class RegisteredCommandRunTest(unittest.TestCase):
    """2. **Runs the `command` string from hooks.json through a shell, as is.**

    An earlier revision executed the script file directly as `[sys.executable, script]`.
    That way the `command` string is **never executed at all** — it passes whether the
    shell wrapper is broken, the quoting is wrong or the variable never expands. That
    checked the ingredients of the thing under test, not the thing itself.

    What this catches:

    - build.sh forgetting to copy a helper (`hook_io`, `repo_identity`) so the hook dies at
      import
    - broken JSON escaping, shell quoting or `${CLAUDE_PLUGIN_ROOT}` expansion in `command`
    - **exit 2 when the script is missing, which blocks the tool call** (issue #107)

    ⚠️ exit 0 alone is not enough: a guard that always skips also exits 0. So for the
    healthy case we additionally check the `HARNESS_HOOK_TRACE` line to see it **really
    fired**.
    """

    def _payload(self, event, matcher, adapter):
        """The minimal input that would realistically arrive for that (event, matcher)."""
        tools = ADAPTERS[adapter]
        candidates = tools["edit"] + tools["shell"]
        tool_name = next((t for t in candidates if _matches(matcher, t)), "Bash")
        data = {"hook_event_name": event, "tool_name": tool_name}
        if tool_name in tools["edit"] and tool_name != "apply_patch":
            data["tool_input"] = {"file_path": "note.txt", "new_string": "hello"}
        elif tool_name == "apply_patch":
            data["tool_input"] = {"command": "*** Begin Patch\n*** Add File: note.txt\n"
                                             "+hello\n*** End Patch"}
        else:
            data["tool_input"] = {"command": "echo hello"}
        if event == "PostToolUse":
            data["tool_response"] = {}
        if event == "UserPromptSubmit":
            data["prompt"] = "hello"
        return data

    def _run(self, command, plugin_root, project, payload, trace=None):
        env = {k: v for k, v in os.environ.items()
               if k not in ("HARNESS_AUTO_REFLECT", "HARNESS_HOOK_TRACE", "REFLECT_JOB")}
        env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
        env["CLAUDE_PROJECT_DIR"] = str(project)
        if trace:
            env["HARNESS_HOOK_TRACE"] = str(trace)
        # The same way the hook runner does it — hand the whole command string to a shell.
        return subprocess.run(["sh", "-c", command], input=json.dumps(payload),
                              capture_output=True, text=True, env=env,
                              cwd=project, timeout=60)

    def test_command_runs_and_the_hook_actually_fires(self):
        for adapter in ADAPTERS:
            bundle = ROOT / "plugins" / adapter
            for event, matcher, command in _command_registrations(adapter):
                with tempfile.TemporaryDirectory() as tmp:
                    project = pathlib.Path(tmp)
                    (project / ".claude" / "memory").mkdir(parents=True)
                    trace = project / "trace.jsonl"
                    proc = self._run(command, bundle, project,
                                     self._payload(event, matcher, adapter), trace)
                    fired = trace.exists() and trace.read_text(encoding="utf-8").strip()
                with self.subTest(adapter=adapter, event=event, command=command[:60]):
                    self.assertEqual(0, proc.returncode,
                                     f"the command for {adapter}/{event} failed — could be a "
                                     f"missing helper cp or a shell quoting problem."
                                     f"\nstderr:\n{proc.stderr}")
                    self.assertTrue(fired,
                                    f"{adapter}/{event}: exit 0 but no record that the hook "
                                    "fired. A guard may always be skipping (e.g. a failed "
                                    "path expansion).")

    def test_missing_script_does_not_block_the_tool_call(self):
        """A missing script must exit 0. **Exit 2 blocks the tool call.**

        A plugin update deletes the old version's cache directory, and hooks of a session
        still pointing there now reference a missing file. `python3 <missing file>` exits 2,
        and 2 means "block" in the hook contract — which is how every shell command got
        blocked (issue #107).
        """
        for adapter in ADAPTERS:
            for event, matcher, command in _command_registrations(adapter):
                with tempfile.TemporaryDirectory() as tmp:
                    root = pathlib.Path(tmp)
                    project = root / "project"
                    (project / ".claude" / "memory").mkdir(parents=True)
                    # A bundle with no scripts at all — exactly the state after an update
                    # wiped the cache.
                    empty_bundle = root / "gone"
                    (empty_bundle / "hooks").mkdir(parents=True)
                    proc = self._run(command, empty_bundle, project,
                                     self._payload(event, matcher, adapter))
                with self.subTest(adapter=adapter, event=event, command=command[:60]):
                    self.assertNotEqual(
                        2, proc.returncode,
                        f"{adapter}/{event}: exits 2 when the script is missing — 2 means "
                        "block in the hook contract, so the user's tool call is denied "
                        "(#107).")
                    self.assertEqual(
                        0, proc.returncode,
                        f"{adapter}/{event}: exits {proc.returncode} when the script is "
                        f"missing. It must be 0 to pass quietly."
                        f"\nstderr:\n{proc.stderr}")


class MatcherCoverageTest(unittest.TestCase):
    """3. Matcher mismatch — passes today. The value is in **detecting a regression**."""

    def _matchers_for(self, adapter, script, event):
        return [m for ev, m, rel in _registrations(adapter)
                if rel.endswith(script) and ev == event]

    def test_memory_search_covers_edit_and_shell(self):
        for adapter, tools in ADAPTERS.items():
            matchers = self._matchers_for(adapter, MEMORY_SEARCH, "PreToolUse")
            self.assertTrue(matchers, f"{adapter}: memory-search is not on PreToolUse")
            for tool in tools["edit"] + tools["shell"]:
                with self.subTest(adapter=adapter, tool=tool):
                    self.assertTrue(any(_matches(m, tool) for m in matchers),
                                    f"{adapter}: the memory-search matcher misses {tool}")

    def test_reflection_covers_edit_tools(self):
        for adapter, tools in ADAPTERS.items():
            matchers = self._matchers_for(adapter, REFLECTION, "PostToolUse")
            self.assertTrue(matchers, f"{adapter}: reflection is not on PostToolUse")
            for tool in tools["edit"]:
                with self.subTest(adapter=adapter, tool=tool):
                    self.assertTrue(any(_matches(m, tool) for m in matchers),
                                    f"{adapter}: the reflection matcher misses {tool}")


class FixtureMatcherCouplingTest(unittest.TestCase):
    """4. hook_io ↔ hooks.json coupling.

    If hook_io recognizes an input as an edit but no matcher accepts that tool name, the
    normalization is perfect and the hook never fires at all. The two files can drift apart
    here, so they are pinned together.
    """

    FIXTURES = [
        ("harness", {"tool_name": "Edit",
                     "tool_input": {"file_path": "a.py", "new_string": "x"}}),
        ("harness", {"tool_name": "Write",
                     "tool_input": {"file_path": "a.py", "content": "x"}}),
        ("harness", {"tool_name": "MultiEdit",
                     "tool_input": {"file_path": "a.py",
                                    "edits": [{"new_string": "x"}]}}),
        # Input measured on codex-cli 0.145.0, from the body of issue #85.
        ("codex", {"tool_name": "apply_patch",
                   "tool_input": {"command": "*** Begin Patch\n"
                                             "*** Add File: /tmp/x/test.txt\n"
                                             "+world\n*** End Patch"},
                   "tool_use_id": "exec-9fa03e9a-13d8-438e-bb96-796a2717a0fe"}),
    ]

    def test_edit_fixtures_reach_the_edit_hooks(self):
        for adapter, payload in self.FIXTURES:
            tool_name = payload["tool_name"]
            with self.subTest(adapter=adapter, tool=tool_name):
                self.assertTrue(edited_files(payload),
                                f"{tool_name}: hook_io does not read this as an edit")
                for script, event in ((MEMORY_SEARCH, "PreToolUse"),
                                      (REFLECTION, "PostToolUse")):
                    matchers = [m for ev, m, rel in _registrations(adapter)
                                if rel.endswith(script) and ev == event]
                    self.assertTrue(
                        any(_matches(m, tool_name) for m in matchers),
                        f"{adapter}: the {script} matcher does not accept {tool_name} — "
                        f"normalization works but the hook never fires")


if __name__ == "__main__":
    unittest.main()
