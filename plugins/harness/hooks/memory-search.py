#!/usr/bin/env python3
"""
PreToolUse hook (Edit|Write|MultiEdit): 편집하려는 파일과 관련된 memory 파일을 미리
읽어 Claude 컨텍스트에 주입한다. "이 파일을 고칠 땐 이 규칙·결정을 기억하라".

엔진/데이터 분리 (하네스 3층 구조):
- **엔진(core, 이 파일)**: 프로젝트 매핑을 읽어 glob/substring 매칭 → 메모리 파일 주입.
- **데이터(프로젝트)**: `$CLAUDE_PROJECT_DIR/.claude/memory/routes.json` 이 "어떤 파일 →
  어떤 메모리" 매핑을 정의한다. 이 파일이 없으면 엔진은 조용히 no-op — 하드코딩된
  프로젝트 특정 매핑(.kt 등)은 core 에 두지 않는다. 예시 매핑은 project-template 에.

routes.json 형식:
  {
    "rules": [
      {"glob": "*.kt",                    "memory": ["patterns/code-quality.md"]},
      {"contains": ["batch","etl"],       "memory": ["decisions/issue-workflow.md"]},
      {"contains": ["git"], "match_empty": true, "memory": ["decisions/git-workflow.md"]}
    ]
  }
- glob:  편집 파일 경로에 fnmatch (예: "*.kt", "*/service/*").
- contains: 경로에 하나라도 포함되면 매칭 (대소문자 무시).
- match_empty: file_path 가 비어있을 때도 매칭 (예: 경로 없는 편집).
- memory: `.claude/memory/` 기준 상대경로. 매칭 시 이 파일들을 읽어 주입.

주의: TOML 대신 JSON — tomllib 는 Python 3.11+ 필요, JSON 은 무의존.
어떤 예외에도 조용히 통과(fail-open) — 편집을 막지 않는다.
"""
import fnmatch
import json
import os
import sys


def _project_dir():
    # 플러그인 배포 시 이 스크립트는 프로젝트 밖(플러그인 루트)에 있으므로 __file__ 기반
    # fallback 은 프로젝트가 아닌 플러그인 dir 을 가리킨다. cwd(훅 실행 위치=프로젝트)로 fallback.
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _load_rules(memory_dir):
    path = os.path.join(memory_dir, "routes.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rules = data.get("rules", []) if isinstance(data, dict) else []
        return rules if isinstance(rules, list) else []
    except Exception:
        return []


def _safe_memory_path(memory_dir, rel):
    """rel 이 memory_dir 안에 머무는 경우에만 절대경로 반환, 아니면 None.
    routes.json 은 프로젝트 제어 데이터라 untrusted repo 에서 절대경로·`..` 로
    임의 로컬 파일(예: ~/.ssh/config)을 모델 컨텍스트에 주입하려는 시도를 차단한다.
    realpath 라 symlink 탈출도 막힌다."""
    if not isinstance(rel, str) or os.path.isabs(rel):
        return None
    base = os.path.realpath(memory_dir)
    full = os.path.realpath(os.path.join(base, rel))
    if full == base or full.startswith(base + os.sep):
        return full
    return None


def _matches(rule, file_path):
    low = file_path.lower()
    if not file_path and rule.get("match_empty"):
        return True
    g = rule.get("glob")
    if g and fnmatch.fnmatch(file_path, g):
        return True
    for sub in rule.get("contains", []) or []:
        if isinstance(sub, str) and sub.lower() in low:
            return True
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    file_path = data.get("tool_input", {}).get("file_path", "") or ""
    memory_dir = os.path.join(_project_dir(), ".claude/memory")

    rules = _load_rules(memory_dir)
    if not rules:
        sys.exit(0)  # 매핑 없음 → no-op (generic 엔진, 프로젝트 데이터 부재)

    # 매칭된 규칙들의 memory 목록을 순서 유지하며 dedup
    rel_paths = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        try:
            if _matches(rule, file_path):
                for rel in rule.get("memory", []) or []:
                    if isinstance(rel, str) and rel not in rel_paths:
                        rel_paths.append(rel)
        except Exception:
            continue

    output = []
    for rel in rel_paths:
        path = _safe_memory_path(memory_dir, rel)  # 경로 탈출 차단
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    output.append(f"[memory/{rel}]\n{f.read().strip()}")
            except Exception:
                continue

    if output:
        # PreToolUse 평문 stdout 은 디버그 로그로만 가고 Claude 에게 도달하지 않는다.
        # additionalContext 로 내보내야 실제로 컨텍스트에 주입된다.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": "\n\n".join(output),
            }
        }))

    sys.exit(0)


if __name__ == "__main__":
    main()
