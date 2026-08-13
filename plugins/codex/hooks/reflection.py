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
    ],
    "packs": [
      {"name": "react-async-timing", "enabled": false, "rules": [...]}
    ]
  }
- glob:  이 규칙을 적용할 파일 (fnmatch, 생략 시 모든 파일).
- globs: 여러 파일 패턴 중 하나에 적용할 때 쓰는 glob 배열.
- regex: 새 코드에서 찾을 패턴 (Python re). 매칭 수(count) 계산.
- enabled: false 면 이 규칙만 비활성.
- min_count: 이 수 이상일 때만 경고 (기본 1).
- message: 경고문. `{count}` 는 매칭 수로 치환.
- packs: opt-in 규칙 묶음. enabled=true 인 pack 의 rules 만 적용.

JSON 사용(무의존). 어떤 예외에도 조용히 통과(fail-open) — 편집 결과를 막지 않는다.
"""
import fnmatch
import json
import os
import re
import sys

# hook_io 는 build.sh 가 이 훅과 같은 디렉토리에 co-locate 한다(repo_identity 와 같은 규약).
# core 소스 트리에서 직접 돌릴 때는 ../scripts 에 있다 — 테스트가 이 경로로 로드한다.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(1, os.path.join(os.path.dirname(_HERE), "scripts"))
from hook_io import edited_files, emit_context  # noqa: E402

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
        rules = data.get("rules", []) if isinstance(data.get("rules"), list) else []
        packs = data.get("packs", []) if isinstance(data.get("packs"), list) else []
        for pack in packs:
            if not isinstance(pack, dict) or pack.get("enabled") is not True:
                continue
            pack_rules = pack.get("rules")
            if isinstance(pack_rules, list):
                rules.extend(pack_rules)
        return {
            "rules": rules,
            "builtins": data.get("builtins", {}) if isinstance(data.get("builtins"), dict) else {},
        }
    except Exception:
        return {"rules": [], "builtins": {}}


def _apply_rule(rule, file_path, content):
    if not isinstance(rule, dict):
        return None
    if rule.get("enabled") is False:
        return None
    if "globs" in rule:
        globs = rule["globs"]
        if isinstance(globs, str):
            patterns = [globs]
        elif isinstance(globs, list):
            patterns = [pattern for pattern in globs if isinstance(pattern, str)]
        else:
            return None
        if not patterns:
            return None
    else:
        if "glob" in rule:
            glob = rule["glob"]
            if not isinstance(glob, str):
                return None
            patterns = [glob]
        else:
            patterns = []
    if patterns and not any(fnmatch.fnmatch(file_path, pattern) for pattern in patterns):
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

    # 내용이 실제로 추가된 파일만 본다. 한 번의 편집이 여러 파일을 건드릴 수 있고
    # (Codex 패치), 삭제는 검사할 새 코드가 없다.
    targets = [f for f in edited_files(data) if f.added]
    if not targets:
        sys.exit(0)

    memory_dir = os.path.join(_project_dir(), ".claude/memory")
    cfg = _load_config(memory_dir)

    # ⚠️ 규칙은 **파일마다 따로** 적용한다. 여러 파일의 추가 내용을 합쳐서 한 번에 돌리면
    # `{"glob": "*.kt"}` 규칙이 .md 파일의 내용까지 보게 된다. 그래서 min_count 와
    # `{count}` 는 **파일 단위** 값이다.
    warnings = []
    for target in targets:
        for warning in _file_warnings(cfg, target.path, target.added):
            if warning not in warnings:   # 같은 경고가 파일마다 반복되면 한 번만
                warnings.append(warning)

    # PostToolUse 평문 stdout 은 모델에게 도달하지 않는다.
    # additionalContext 로 내보내야 tool result 옆에 주입된다(키 형태는 hook_io 참고).
    if warnings:
        emit_context("PostToolUse", "## Reflection\n" + "\n".join(warnings))
    sys.exit(0)


def _file_warnings(cfg, file_path, content):
    """파일 하나에 대한 경고 목록."""
    out = []
    # 내장 범용 규칙: TODO/FIXME (끄지 않은 경우)
    if cfg["builtins"].get("todo_fixme", True) and re.search(r"TODO|FIXME", content):
        out.append(TODO_MESSAGE)
    # 프로젝트 정의 규칙
    for rule in cfg["rules"]:
        try:
            warning = _apply_rule(rule, file_path, content)
            if warning:
                out.append(warning)
        except Exception:
            continue
    return out


if __name__ == "__main__":
    main()
