#!/usr/bin/env python3
"""
PostToolUse hook (Edit|Write|MultiEdit): 방금 쓴 코드에 대해 간단한 품질 경고를
tool result 옆에 주입한다. "이거 이렇게 두면 나중에 문제" 를 즉시 상기.

엔진/데이터 분리 (하네스 3층 구조):
- **엔진(core, 이 파일)**: 정규식 규칙을 새 코드 내용에 적용해 경고문 생성.
- **데이터(프로젝트)**: `$CLAUDE_PROJECT_DIR/.claude/memory/reflection-rules.json` 이
  언어·팀 특정 규칙(예: Kotlin `!!`/`var`)을 정의한다. 없으면 내장 범용 규칙만.
  Kotlin 등 언어 전용 규칙은 core 에 두지 않는다 — 예시는 project-template 에.

내장 범용 규칙: TODO/FIXME 잔존 경고 (모든 파일, 언어 무관). 끄려면 rules 파일에
`"builtins": {"todo_fixme": false}`.

reflection-rules.json 형식:
  {
    "rules": [
      {"glob": "*.kt", "regex": "!!",
       "message": "`!!` 사용 {count}곳 — requireNotNull 또는 ?: return 으로 교체 검토"},
      {"glob": "*.kt", "regex": "(?m)^\\s*var ", "min_count": 3,
       "message": "var 선언 다수({count}) — fold/associate/sumOf 등으로 대체 검토"}
    ]
  }
- glob:  이 규칙을 적용할 파일 (fnmatch, 생략 시 모든 파일).
- regex: 새 코드에서 찾을 패턴 (Python re). 매칭 수(count) 계산.
- min_count: 이 수 이상일 때만 경고 (기본 1).
- message: 경고문. `{count}` 는 매칭 수로 치환.

JSON 사용(무의존). 어떤 예외에도 조용히 통과(fail-open) — 편집 결과를 막지 않는다.
"""
import fnmatch
import json
import os
import re
import sys

TODO_MESSAGE = "⚠️  TODO/FIXME 남아있음 — 작업 완료 후 제거 필요"


def _project_dir():
    # 플러그인 배포 시 이 스크립트는 프로젝트 밖(플러그인 루트)에 있으므로 __file__ 기반
    # fallback 은 프로젝트가 아닌 플러그인 dir 을 가리킨다. cwd(훅 실행 위치=프로젝트)로 fallback.
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _load_config(memory_dir):
    path = os.path.join(memory_dir, "reflection-rules.json")
    if not os.path.exists(path):
        return {"rules": [], "builtins": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"rules": [], "builtins": {}}
        return {
            "rules": data.get("rules", []) if isinstance(data.get("rules"), list) else [],
            "builtins": data.get("builtins", {}) if isinstance(data.get("builtins"), dict) else {},
        }
    except Exception:
        return {"rules": [], "builtins": {}}


def _apply_rule(rule, file_path, content):
    if not isinstance(rule, dict):
        return None
    glob = rule.get("glob")
    if glob and not fnmatch.fnmatch(file_path, glob):
        return None
    regex = rule.get("regex")
    msg = rule.get("message")
    if not regex or not msg:
        return None
    try:
        count = len(re.findall(regex, content))
    except re.error:
        return None
    if count < int(rule.get("min_count", 1)):
        return None
    return "⚠️  " + msg.replace("{count}", str(count))


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    ti = data.get("tool_input", {}) or {}
    file_path = ti.get("file_path", "") or ""
    # Edit: new_string / Write: content / MultiEdit: edits[*].new_string (합침).
    content = ti.get("new_string", "") or ti.get("content", "")
    if not content:
        edits = ti.get("edits")
        if isinstance(edits, list):
            content = "\n".join(
                e.get("new_string", "") for e in edits
                if isinstance(e, dict) and e.get("new_string")
            )
    if not content:
        sys.exit(0)

    memory_dir = os.path.join(_project_dir(), ".claude/memory")
    cfg = _load_config(memory_dir)

    warnings = []

    # 내장 범용 규칙: TODO/FIXME (끄지 않은 경우)
    if cfg["builtins"].get("todo_fixme", True) and re.search(r"TODO|FIXME", content):
        warnings.append(TODO_MESSAGE)

    # 프로젝트 정의 규칙
    for rule in cfg["rules"]:
        try:
            w = _apply_rule(rule, file_path, content)
            if w:
                warnings.append(w)
        except Exception:
            continue

    if warnings:
        # PostToolUse 평문 stdout 은 Claude 에게 도달하지 않는다.
        # additionalContext 로 내보내야 tool result 옆에 주입된다.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "## Reflection\n" + "\n".join(warnings),
            }
        }))

    sys.exit(0)


if __name__ == "__main__":
    main()
