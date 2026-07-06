#!/usr/bin/env bash
# core/ (정본 템플릿) → 각 툴 어댑터로 렌더링 생성. symlink 대신 렌더(크로스플랫폼·툴별 문구 정확).
# core 수정 후 항상 실행하고 생성물까지 함께 커밋한다. CI 가 drift 를 검사한다.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# SKILL.md 의 {{PLACEHOLDER}} 를 어댑터별 값으로 치환 (sed 구분자 | — 값에 / 포함 대비)
render() { # $1=src  $2=dst   (env: AGENT RULES_FILE HANDOFF DEEP_RECOVERY PATH_NOTE)
  sed -e "s|{{AGENT}}|$AGENT|g" \
      -e "s|{{RULES_FILE}}|$RULES_FILE|g" \
      -e "s|{{HANDOFF}}|$HANDOFF|g" \
      -e "s|{{DEEP_RECOVERY}}|$DEEP_RECOVERY|g" \
      -e "s|{{PATH_NOTE}}|$PATH_NOTE|g" \
      "$1" > "$2"
}

SKILLS=$(cd core/skills && ls -d */ | sed 's#/##')

# ── Claude 어댑터: plugins/harness ──────────────────────────────
# 스크립트는 bin/ 공유(플러그인 활성 시 PATH 등록 — 검증됨).
rm -rf plugins/harness/skills plugins/harness/bin plugins/harness/hooks
mkdir -p plugins/harness/bin
cp core/scripts/handoff.py plugins/harness/bin/agent-handoff
chmod +x plugins/harness/bin/agent-handoff
AGENT=claude; RULES_FILE=CLAUDE.md; HANDOFF=agent-handoff
DEEP_RECOVERY='`/fw-claude` 또는 `/continue-claude`'
PATH_NOTE=''   # Claude: bin/ 이 PATH 등록되어 cwd 무관
for s in $SKILLS; do
  mkdir -p "plugins/harness/skills/$s"
  render "core/skills/$s/SKILL.md" "plugins/harness/skills/$s/SKILL.md"
done

# 훅: core/hooks/*.py 를 그대로 번들(스크립트끼리 co-locate — 훅이 dirname(__file__) 로
# reflect.py 를 찾고, reflect.py 가 compact_transcript.py 를 찾는다). Python 은 generic 이라
# placeholder 렌더 불필요. hooks.json 은 ${CLAUDE_PLUGIN_ROOT} 로 이 번들을 참조.
# ⚠️ Codex 훅은 pass 1 미포함(버전 취약 openai/codex#19385·#21639) — 스킬만 양쪽 배포. (이슈 #1)
mkdir -p plugins/harness/hooks
cp core/hooks/*.py plugins/harness/hooks/
chmod +x plugins/harness/hooks/*.py
cat > plugins/harness/hooks/hooks.json <<'HOOKS_JSON'
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Edit|Write|MultiEdit", "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/memory-search.py\"" } ] },
      { "matcher": "Bash", "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/pre-push-merged-guard.py\"" } ] }
    ],
    "PostToolUse": [
      { "matcher": "Edit|Write|MultiEdit", "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/reflection.py\"" } ] },
      { "matcher": "Bash", "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/pr-merge-reflect.py\"" } ] }
    ],
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/pr-merge-reflect.py\"" } ] }
    ],
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/pr-merge-reflect.py\"" } ] }
    ]
  }
}
HOOKS_JSON

# ── Codex 어댑터: codex/ (skill-only plugin) ────────────────────
# 스크립트는 스킬 폴더에 번들(scripts/) — bin PATH 가정 회피(Codex 미검증 영역).
rm -rf codex/skills codex/bin
AGENT=codex; RULES_FILE=AGENTS.md; HANDOFF='python3 scripts/handoff.py'
DEEP_RECOVERY='`~/.codex/sessions` 의 최근 세션 로그'
# Codex: 위 경로는 이 SKILL.md 가 있는 스킬 폴더 기준 상대경로 — 실행 workdir 를 그 폴더로
PATH_NOTE='> ⚠️ 위 명령의 `scripts/handoff.py` 는 **이 SKILL.md 가 있는 스킬 디렉토리 기준 상대경로**다. Bash 실행 시 workdir 를 그 스킬 폴더로 두고 실행하라.'
for s in $SKILLS; do
  mkdir -p "codex/skills/$s/scripts"
  cp core/scripts/handoff.py "codex/skills/$s/scripts/handoff.py"
  render "core/skills/$s/SKILL.md" "codex/skills/$s/SKILL.md"
done

# 렌더 후 미치환 placeholder 가드
if grep -rl '{{' plugins/harness/skills codex/skills 2>/dev/null | grep -q .; then
  echo "ERROR: 미치환 placeholder 남음"; grep -rn '{{' plugins/harness/skills codex/skills; exit 1
fi
echo "빌드 완료: core → Claude(plugins/harness, bin PATH) + Codex(codex/, skill별 scripts 번들)"
