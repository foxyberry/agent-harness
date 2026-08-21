#!/usr/bin/env python3
"""
SessionStart hook: 프로젝트 공유 메모리 인덱스(.claude/memory/INDEX.md)를 세션
초반에 노출한다.

목표는 memory 본문 전체를 밀어 넣는 것이 아니라, "어떤 공유 메모리가 있는지"를
에이전트가 놓치지 않게 하는 것이다. 실제 세부 규칙은 기존 memory-search 훅이
편집 파일에 맞춰 주입한다.

설정(선택): $CLAUDE_PROJECT_DIR/.claude/memory/index-load.json
  {
    "enabled": true,
    "max_chars": 12000
  }

기본값은 enabled=true, max_chars=12000. .claude/memory/INDEX.md 가 없으면 no-op.
어떤 예외에도 조용히 통과(fail-open)한다.
"""
import json
import os
import sys

# hook_io 는 build.sh 가 이 훅과 같은 디렉토리에 co-locate 하는 **필수 의존**이다.
# project_dir 해석 정본까지 여기 있으므로 누락된 깨진 설치본에서 로컬 fallback 으로 계속
# 실행하면 훅마다 계약이 다시 갈린다. core 소스 트리에서 직접 실행할 때만 ../scripts 를 본다.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(1, os.path.join(os.path.dirname(_HERE), "scripts"))
from hook_io import project_dir as _project_dir, trace_entry  # noqa: E402

DEFAULT_MAX_CHARS = 12000
MAX_CAP = 50000


def _safe_child_path(parent, name):
    """parent/name 이 parent 안에 머무는 경우에만 반환한다.

    INDEX.md 는 SessionStart 에 자동 주입되므로, untrusted repo 가 symlink 로
    .claude/memory 밖 로컬 파일을 모델 컨텍스트에 넣는 경로 탈출을 막는다.
    """
    if os.path.sep in name or (os.path.altsep and os.path.altsep in name):
        return None
    base = os.path.realpath(parent)
    full = os.path.realpath(os.path.join(parent, name))
    if full == base or full.startswith(base + os.sep):
        return full
    return None


def _safe_memory_dir(project_dir):
    """프로젝트 내부의 .claude/memory 만 허용한다.

    프로젝트가 아닌 위치로 symlink 된 memory 디렉터리는 자동 주입 대상에서 제외한다.
    """
    project = os.path.realpath(project_dir)
    memory = os.path.realpath(os.path.join(project_dir, ".claude/memory"))
    if memory == project or memory.startswith(project + os.sep):
        return memory
    return None


def _load_config(memory_dir):
    cfg = {"enabled": True, "max_chars": DEFAULT_MAX_CHARS}
    path = _safe_child_path(memory_dir, "index-load.json")
    if not path:
        return cfg
    if not os.path.exists(path):
        return cfg
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return cfg
        if isinstance(data.get("enabled"), bool):
            cfg["enabled"] = data["enabled"]
        if isinstance(data.get("max_chars"), int):
            cfg["max_chars"] = min(max(data["max_chars"], 1000), MAX_CAP)
    except Exception:
        return cfg
    return cfg


def _read_index(index_path, max_chars):
    try:
        with open(index_path, encoding="utf-8") as f:
            text = f.read(max_chars + 1).strip()
    except Exception:
        return None
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars].rstrip()
        + f"\n\n[truncated: .claude/memory/INDEX.md exceeds {max_chars} chars]"
    )


def main():
    if os.environ.get("REFLECT_JOB") == "1":
        sys.exit(0)

    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    event = data.get("hook_event_name") or data.get("hookEventName")
    trace_entry(__file__, event)
    if event != "SessionStart":
        sys.exit(0)

    project_dir = _project_dir(data)
    memory_dir = _safe_memory_dir(project_dir)
    if not memory_dir:
        sys.exit(0)
    index_path = _safe_child_path(memory_dir, "INDEX.md")
    if not index_path:
        sys.exit(0)
    if not os.path.exists(index_path):
        sys.exit(0)

    cfg = _load_config(memory_dir)
    if not cfg["enabled"]:
        sys.exit(0)

    index = _read_index(index_path, cfg["max_chars"])
    if not index:
        sys.exit(0)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "## Project Shared Memory Index\n"
                "The project has committed shared memory at `.claude/memory/`. "
                "Use this index to discover relevant rules and decisions; read the "
                "referenced memory files when they are relevant to the current task.\n\n"
                f"[memory/INDEX.md]\n{index}"
            ),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
