#!/usr/bin/env python3
"""편집 훅의 **입력 정규화**와 **출력 방출**을 Claude·Codex 공용으로 맞춘다.

입력은 툴마다 모양이 다르고(아래), 출력은 툴마다 읽는 키가 다를 수 있다(`emit_context`).
둘 다 훅마다 따로 쓰면 한쪽만 고치는 사고가 난다 — 한 곳에 모은다.

## 입력 정규화

편집 훅(memory-search·reflection)이 알아야 하는 건 딱 두 가지다 —
**어떤 파일을 고쳤나**, **뭘 새로 넣었나**. 그런데 그 정보가 오는 모양이 툴마다 다르다.

| 툴 | tool_name | 어디에 담기나 |
|---|---|---|
| Claude | `Edit` | `tool_input.file_path` + `new_string` |
| Claude | `Write` | `tool_input.file_path` + `content` |
| Claude | `MultiEdit` | `tool_input.file_path` + `edits[*].new_string` |
| Codex | `apply_patch` | `tool_input.command` 에 **패치 원문 그대로** |

Codex 의 `command` 는 JS 래퍼가 아니라 apply_patch 텍스트 자체다(0.145.0 실측):

    *** Begin Patch
    *** Add File: /tmp/x/test.txt
    +world
    *** End Patch

**한 번의 편집이 여러 파일을 건드릴 수 있다** — Codex 패치 하나에 `Add File` 셋이 들어갈 수
있다. 그래서 이 모듈은 항상 **목록**을 돌려준다. 훅은 파일마다 규칙을 적용한다.

어떤 예외에도 빈 목록으로 떨어진다(fail-open) — 정규화 실패가 편집을 막으면 안 된다.
"""
import json
import os
import re
import sys

# `*** Add File: path` / `*** Update File: path` / `*** Delete File: path` / `*** Move to: path`
_FILE_MARKER = re.compile(r"^\*\*\*\s+(Add|Update|Delete)\s+File:\s*(.+?)\s*$")
_MOVE_MARKER = re.compile(r"^\*\*\*\s+Move\s+to:\s*(.+?)\s*$")


class EditedFile:
    """편집된 파일 하나. `path` 는 빈 문자열일 수 있다(경로를 못 얻은 편집)."""

    __slots__ = ("path", "added")

    def __init__(self, path="", added=""):
        self.path = path or ""
        self.added = added or ""

    def __repr__(self):  # 테스트 실패 메시지용
        return f"EditedFile(path={self.path!r}, added={self.added[:40]!r})"

    def __eq__(self, other):
        return (isinstance(other, EditedFile)
                and self.path == other.path and self.added == other.added)


def edited_files(data):
    """훅 입력(stdin JSON dict) → [EditedFile]. 편집이 아니면 빈 목록.

    tool_name 으로 분기하지 않는다 — 툴마다 이름이 다르고 새 이름이 생길 수 있다.
    **담긴 모양**으로 판정한다: `file_path` 가 있으면 Claude 계열, `command` 가 패치면 Codex.
    """
    try:
        ti = (data or {}).get("tool_input") or {}
        if not isinstance(ti, dict):
            return []

        file_path = ti.get("file_path")
        if isinstance(file_path, str) and file_path:
            return [EditedFile(file_path, _claude_added(ti))]

        # 셸이라고 이름이 말해주면 패치처럼 생겼어도 편집이 아니다 — 패치를 인용한
        # `gh pr create --body "...*** Begin Patch..."` 를 편집으로 파싱하면 있지도 않은
        # 파일로 라우팅한다. 반대 방향은 shell_command() 에 같은 설명이 있다.
        if _is_named(data, "Bash"):
            return []

        command = ti.get("command")
        if isinstance(command, str) and "*** Begin Patch" in command:
            return parse_apply_patch(command)

        return []
    except Exception:
        return []


def _claude_added(ti):
    """Edit=new_string · Write=content · MultiEdit=edits[*].new_string(합침)."""
    for key in ("new_string", "content"):
        value = ti.get(key)
        if isinstance(value, str) and value:
            return value
    edits = ti.get("edits")
    if isinstance(edits, list):
        parts = [
            e.get("new_string", "") for e in edits
            if isinstance(e, dict) and isinstance(e.get("new_string"), str)
        ]
        return "\n".join(p for p in parts if p)
    return ""


def parse_apply_patch(command):
    """apply_patch 원문 → [EditedFile]. 파일별로 추가된 줄만 모은다.

    - `*** Update File:` 뒤에 `*** Move to:` 가 오면 **목적지 경로**로 잡는다.
      내용이 최종적으로 사는 곳이 거기다.
    - `*** Delete File:` 은 추가 내용이 없다. 그래도 목록에는 넣는다 — memory-search 는
      "이 파일을 건드릴 때 이 규칙을 봐라" 라서 삭제도 대상이다. reflection 은 내용이
      없으면 알아서 건너뛴다.
    - 추가된 줄은 `+` 로 시작하는 것만 **고른다**(`-`/context/`@@`/`***` 를 빼는 게 아니라).
      제외 목록으로 만들면 새 마커가 생겼을 때 내용에 섞여 들어온다.
    """
    files = []
    current = None
    added = []

    def flush():
        if current is not None:
            files.append(EditedFile(current, "\n".join(added)))

    for line in (command or "").splitlines():
        marker = _FILE_MARKER.match(line)
        if marker:
            flush()
            current, added = marker.group(2), []
            continue

        move = _MOVE_MARKER.match(line)
        if move and current is not None:
            current = move.group(1)   # 목적지가 최종 경로
            continue

        if line.startswith("***"):    # Begin/End Patch 등 나머지 마커
            continue

        # `+` 하나를 떼면 나머지가 그대로 추가된 줄이다.
        # ⚠️ `+++` 를 unified diff 헤더로 보고 버리면 안 된다. apply_patch 는 파일을
        # `*** ... File:` 마커로 표시하고 `+++ b/path` 헤더를 **쓰지 않는다**. 반면 실제
        # 코드에는 `++counter;` 처럼 `++` 로 시작하는 줄이 있고, 그건 패치에서 `+++counter;`
        # 가 된다 — 헤더인 줄 알고 버리면 그 코드가 검사에서 조용히 빠진다.
        if current is not None and line.startswith("+"):
            added.append(line[1:])

    flush()
    return files


def _is_named(data, name):
    """`tool_name` 이 정확히 이것인가. 이름이 없거나 다르면 False."""
    return ((data or {}).get("tool_name") or "") == name


def shell_command(data):
    """셸 명령이면 그 원문, 아니면 None.

    memory-search 가 `Bash` 에도 걸리게 되면서 필요해졌다 — "파일을 고칠 때"가 아니라
    "이 명령을 실행할 때" 상기시켜야 하는 규칙이 있다(예: PR 만들기 전에 리뷰 결과를
    댓글로 남겨라). 그런 규칙은 편집 시점에 띄우면 필요한 순간에 닿지 않는다(이슈 #90).

    ⚠️ 편집(`apply_patch`)도 `tool_input.command` 에 담겨서 모양만으로는 안 갈린다.
    그래서 **이름이 결정적일 때는 이름을 믿고, 아니면 모양으로 떨어진다**:

    1. `tool_name == "apply_patch"` → 편집이다
    2. `tool_name == "Bash"` → 셸이다. **명령 안에 패치 문자열이 들어 있어도 셸이다** —
       `gh pr create --body "...*** Begin Patch..."` 처럼 패치를 인용하는 명령이 실제로
       있고, 이걸 편집으로 오인하면 **바로 그 순간**에 규칙 주입이 조용히 빠진다(Codex 리뷰)
    3. 이름이 없거나 모르는 이름 → 패치 마커로 판정

    `edited_files` 가 이름으로 분기하지 않는 것과 다른 이유: 편집 도구는 이름이 여럿이고
    (`Edit`/`Write`/`MultiEdit`/`apply_patch`) 새로 생기지만, 셸은 양쪽 다 `Bash` 하나로
    관측됐다. 이름이 실제로 결정적인 자리에서만 이름을 쓴다.
    """
    try:
        ti = (data or {}).get("tool_input") or {}
        if not isinstance(ti, dict):
            return None
        command = ti.get("command")
        if not isinstance(command, str) or not command:
            return None
        if _is_named(data, "Bash"):
            return command
        if _is_named(data, "apply_patch") or ti.get("file_path"):
            return None
        return command if "*** Begin Patch" not in command else None
    except Exception:
        return None


def added_content(data):
    """편집 전체에서 추가된 내용을 하나로 (파일 구분이 필요 없는 호출자용)."""
    return "\n".join(f.added for f in edited_files(data) if f.added)


def edited_paths(data):
    """편집된 파일 경로 목록 (내용이 필요 없는 호출자용)."""
    return [f.path for f in edited_files(data)]


def emit_context(event, text):
    """모델 컨텍스트에 주입할 텍스트를 stdout 으로 낸다. 빈 텍스트면 아무것도 안 낸다.

    **키를 두 벌 낸다** — 중첩(`hookSpecificOutput.additionalContext`)과 최상위
    (`additionalContext`).

    Claude 는 중첩 형태를 읽는다(실증). Codex 문서는 `PreToolUse`/`PostToolUse` 의 출력으로
    `additionalContext` 를 나열하는데 **중첩인지 최상위인지 명시하지 않는다.** 중첩이 동작한
    것을 확인한 건 `SessionStart` 뿐이고, 그건 평문 stdout 도 먹는 이벤트라 중첩 경로를
    제대로 시험한 적이 없다.

    둘 다 내면 어느 쪽이 정답이어도 맞고, 모르는 키는 양쪽 파서가 무시한다. 이 실패 모드는
    **성공과 구별이 안 되기 때문에**(주입 안 돼도 훅은 조용히 성공한다) 추측으로 하나만
    고르지 않는다. 대상 환경에서 실제 주입을 관측하면 그때 한쪽으로 줄인다.
    """
    if not text:
        return
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": text},
        "additionalContext": text,
    }, ensure_ascii=False))
    sys.stdout.flush()


def trace_entry(script_path, event=None):
    """훅이 **실행됐다는 사실**을 파일에 한 줄 남긴다. `HARNESS_HOOK_TRACE` 가 있을 때만.

    무음 실패를 사람이 못 알아채는 이유는 "안 돌았다"와 "돌았는데 할 말이 없었다"가
    바깥에서 똑같이 생겼기 때문이다. matcher 가 어긋나서 훅이 아예 안 떠도, 라우트에
    안 걸려서 아무것도 주입 안 해도, 화면에는 똑같이 아무것도 안 나온다.

    그래서 **주입 시점이 아니라 진입 시점**에 남긴다. `emit_context` 에 넣으면 위 두 경우가
    또 같아져서 아무것도 못 가린다.

    평소에는 환경변수가 없어 아무 일도 안 한다. 크로스 프로젝트 검증(이슈 #85 4단계)에서만
    켠다:

        HARNESS_HOOK_TRACE=/tmp/hook-trace.jsonl codex   # 또는 claude

    어떤 예외에도 조용히 넘어간다 — 진단 장치가 훅을 죽이면 본말전도다.
    """
    path = os.environ.get("HARNESS_HOOK_TRACE")
    if not path:
        return
    try:
        import time
        record = {
            "hook": os.path.basename(script_path or ""),
            "event": event or "",
            "pid": os.getpid(),
            "ts": time.time(),
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
