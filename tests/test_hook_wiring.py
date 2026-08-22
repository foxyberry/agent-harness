"""훅 배선의 **무음 실패**를 잡는다 (이슈 #85 4단계, in-repo 부분).

무음 실패란 훅이 안 돌았는데 아무 일도 일어나지 않아 사람이 못 알아채는 상태다.
경로 오타·helper 미복사·matcher 불일치가 다 여기로 떨어진다 — 셋 다 화면에는
"조용히 성공"으로 보인다.

여기서 잡는 것 (전부 이 저장소 안에서 결정론적으로 확인 가능한 것):

1. hooks.json 이 가리키는 스크립트가 그 번들에 실제로 있나 (경로 오타)
2. 등록된 훅을 **번들 디렉토리에서 실행**해서 exit 0 인가 (helper cp 누락 → import 죽음)
3. matcher 가 그 툴이 실제로 내보내는 도구 이름을 덮나 (matcher 불일치)
4. 편집 픽스처가 편집 훅 matcher 와 어긋나지 않나 (hook_io ↔ hooks.json 커플링)

**여기서 못 잡는 것**: 설치본이 미신뢰라 skip 되는 것, 실제 툴이 훅을 정말 띄우는지.
둘 다 설치 상태·런타임이라 이 저장소의 pytest 가 볼 수 없다. 그건 `HARNESS_HOOK_TRACE`
로 별도 프로젝트에서 관측한다 — 절차는 docs/codex-hooks.md.
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

# 어댑터별 **도구 이름 인벤토리**.
#
# ⚠️ 이 목록을 matcher 에서 뽑아내면 안 된다 — 그러면 자기가 자기를 검사하는 순환이라
# 아무것도 못 잡는다. 출처는 실측이다:
#   - Claude: Edit/Write/MultiEdit/Bash (하네스가 쓰는 편집·셸 도구)
#   - Codex: apply_patch/Bash — 이슈 #85 본문의 codex-cli 0.145.0 실측.
#     rollout 로그의 `exec` 는 도구 이름이 아니라 tool_use_id 접두사였다.
ADAPTERS = {
    "harness": {"edit": ["Edit", "Write", "MultiEdit"], "shell": ["Bash"]},
    "codex": {"edit": ["apply_patch"], "shell": ["Bash"]},
}

# 편집 훅. memory-search 는 셸에도 걸려야 하고(이슈 #90), reflection 은 편집만 본다.
MEMORY_SEARCH = "memory-search.py"
REFLECTION = "reflection.py"

BUILD_HINT = "hooks.json 이 소스와 어긋났다 — `./build.sh` 를 돌리고 생성물까지 커밋할 것."

_COMMAND_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"']+)")


def _hooks_json(adapter):
    path = ROOT / "plugins" / adapter / "hooks" / "hooks.json"
    if not path.exists():
        raise unittest.SkipTest(f"{path} 없음 — {BUILD_HINT}")
    return json.loads(path.read_text(encoding="utf-8"))["hooks"]


def _registrations(adapter):
    """[(event, matcher, script_rel_path)] — 등록된 훅을 평평하게 편다."""
    out = []
    for event, entries in _hooks_json(adapter).items():
        for entry in entries:
            matcher = entry.get("matcher") or ""
            for hook in entry.get("hooks", []):
                found = _COMMAND_RE.search(hook.get("command", ""))
                assert found, f"{adapter}/{event}: ${{CLAUDE_PLUGIN_ROOT}} 상대경로가 아니다"
                out.append((event, matcher, found.group(1)))
    return out


def _command_registrations(adapter):
    """[(event, matcher, command)] — 실행할 command 문자열까지 함께."""
    out = []
    for event, entries in _hooks_json(adapter).items():
        for entry in entries:
            matcher = entry.get("matcher") or ""
            for hook in entry.get("hooks", []):
                out.append((event, matcher, hook["command"]))
    return out


def _matches(matcher, tool_name):
    """Codex·Claude 공통: matcher 는 도구 이름에 대한 정규식, 빈 값이면 전부 매칭."""
    if matcher in ("", "*"):
        return True
    return re.search(matcher, tool_name) is not None


class RegisteredPathsTest(unittest.TestCase):
    """1. 경로 오타 — hooks.json 이 없는 파일을 가리키면 훅은 영원히 안 돈다."""

    def test_every_registered_script_exists_in_its_bundle(self):
        for adapter in ADAPTERS:
            bundle = ROOT / "plugins" / adapter
            for event, _matcher, rel in _registrations(adapter):
                with self.subTest(adapter=adapter, event=event, script=rel):
                    self.assertTrue((bundle / rel).is_file(),
                                    f"{adapter}: {rel} 이 번들에 없다. {BUILD_HINT}")

    def test_codex_merge_hook_cannot_spawn_reflection_job(self):
        """3a에서는 탐지·큐만 배포한다. reflect.py가 들어오면 live rollout 중복 회고가 열린다."""
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
    """2. **hooks.json 의 `command` 문자열을 그대로 셸에서 돌린다.**

    예전 판은 스크립트 파일을 `[sys.executable, script]` 로 직접 실행했다. 그러면 `command`
    문자열은 **한 번도 실행되지 않는다** — 셸 래퍼가 깨졌든, 인용이 틀렸든, 변수가 안
    풀렸든 통과한다. 검사 대상이 아니라 검사 대상의 재료를 본 셈이다.

    여기서 잡는 것:

    - build.sh 가 helper(`hook_io`·`repo_identity`) 복사를 빠뜨려 훅이 import 에서 죽는 것
    - `command` 의 JSON 이스케이프·셸 인용·`${CLAUDE_PLUGIN_ROOT}` 확장이 깨진 것
    - **스크립트가 없을 때 exit 2 가 나와 도구 호출이 차단되는 것** (이슈 #107)

    ⚠️ exit 0 만 보면 안 된다. 가드가 항상 건너뛰어도 exit 0 이다. 그래서 정상 경우에는
    `HARNESS_HOOK_TRACE` 줄까지 확인해 **실제로 떴다**는 것을 본다.
    """

    def _payload(self, event, matcher, adapter):
        """그 (event, matcher) 에 실제로 올 법한 최소 입력."""
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
        # 훅 러너와 같은 방식으로 — command 문자열을 셸에 통째로 넘긴다.
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
                                     f"{adapter}/{event} 의 command 가 실패했다 — helper cp 누락이나 "
                                     f"셸 인용 문제일 수 있다.\nstderr:\n{proc.stderr}")
                    self.assertTrue(fired,
                                    f"{adapter}/{event}: exit 0 이지만 훅이 뜬 기록이 없다. "
                                    "가드가 항상 건너뛰고 있을 수 있다 (경로 확장 실패 등).")

    def test_missing_script_does_not_block_the_tool_call(self):
        """스크립트가 없으면 exit 0 이어야 한다. **2 가 나오면 도구 호출이 차단된다.**

        플러그인이 업데이트되면 옛 버전 캐시 디렉터리가 지워지고, 그 경로를 물고 있던 세션의
        훅은 없는 파일을 가리키게 된다. `python3 <없는 파일>` 은 exit 2 를 내고, 훅 계약에서
        2 는 "차단" 이다 — 그래서 셸 명령이 전부 막혔다 (이슈 #107).
        """
        for adapter in ADAPTERS:
            for event, matcher, command in _command_registrations(adapter):
                with tempfile.TemporaryDirectory() as tmp:
                    root = pathlib.Path(tmp)
                    project = root / "project"
                    (project / ".claude" / "memory").mkdir(parents=True)
                    # 스크립트가 하나도 없는 번들 — 업데이트로 캐시가 지워진 상태 그대로.
                    empty_bundle = root / "gone"
                    (empty_bundle / "hooks").mkdir(parents=True)
                    proc = self._run(command, empty_bundle, project,
                                     self._payload(event, matcher, adapter))
                with self.subTest(adapter=adapter, event=event, command=command[:60]):
                    self.assertNotEqual(
                        2, proc.returncode,
                        f"{adapter}/{event}: 스크립트가 없을 때 exit 2 다 — 훅 계약에서 2 는 "
                        "차단이라 사용자의 도구 호출이 막힌다 (#107).")
                    self.assertEqual(
                        0, proc.returncode,
                        f"{adapter}/{event}: 스크립트가 없을 때 exit {proc.returncode} 다. "
                        f"0 이어야 조용히 지나간다.\nstderr:\n{proc.stderr}")


class MatcherCoverageTest(unittest.TestCase):
    """3. matcher 불일치 — 오늘은 통과한다. 값어치는 **회귀 감지**에 있다."""

    def _matchers_for(self, adapter, script, event):
        return [m for ev, m, rel in _registrations(adapter)
                if rel.endswith(script) and ev == event]

    def test_memory_search_covers_edit_and_shell(self):
        for adapter, tools in ADAPTERS.items():
            matchers = self._matchers_for(adapter, MEMORY_SEARCH, "PreToolUse")
            self.assertTrue(matchers, f"{adapter}: memory-search 가 PreToolUse 에 없다")
            for tool in tools["edit"] + tools["shell"]:
                with self.subTest(adapter=adapter, tool=tool):
                    self.assertTrue(any(_matches(m, tool) for m in matchers),
                                    f"{adapter}: memory-search matcher 가 {tool} 을 놓친다")

    def test_reflection_covers_edit_tools(self):
        for adapter, tools in ADAPTERS.items():
            matchers = self._matchers_for(adapter, REFLECTION, "PostToolUse")
            self.assertTrue(matchers, f"{adapter}: reflection 이 PostToolUse 에 없다")
            for tool in tools["edit"]:
                with self.subTest(adapter=adapter, tool=tool):
                    self.assertTrue(any(_matches(m, tool) for m in matchers),
                                    f"{adapter}: reflection matcher 가 {tool} 을 놓친다")


class FixtureMatcherCouplingTest(unittest.TestCase):
    """4. hook_io ↔ hooks.json 커플링.

    hook_io 가 편집으로 인식하는 입력인데 matcher 가 그 도구 이름을 안 받으면, 정규화는
    완벽한데 훅이 애초에 안 뜬다. 두 파일이 따로 놀 수 있는 자리라 묶어 둔다.
    """

    FIXTURES = [
        ("harness", {"tool_name": "Edit",
                     "tool_input": {"file_path": "a.py", "new_string": "x"}}),
        ("harness", {"tool_name": "Write",
                     "tool_input": {"file_path": "a.py", "content": "x"}}),
        ("harness", {"tool_name": "MultiEdit",
                     "tool_input": {"file_path": "a.py",
                                    "edits": [{"new_string": "x"}]}}),
        # 이슈 #85 본문의 codex-cli 0.145.0 실측 입력.
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
                                f"{tool_name}: hook_io 가 편집으로 못 읽는다")
                for script, event in ((MEMORY_SEARCH, "PreToolUse"),
                                      (REFLECTION, "PostToolUse")):
                    matchers = [m for ev, m, rel in _registrations(adapter)
                                if rel.endswith(script) and ev == event]
                    self.assertTrue(
                        any(_matches(m, tool_name) for m in matchers),
                        f"{adapter}: {script} matcher 가 {tool_name} 을 안 받는다 — "
                        f"정규화는 되는데 훅이 안 뜬다")


if __name__ == "__main__":
    unittest.main()
