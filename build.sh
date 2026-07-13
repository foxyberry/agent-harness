#!/usr/bin/env bash
# core/ (정본 템플릿) → 각 툴 어댑터로 렌더링 생성. symlink 대신 렌더(크로스플랫폼·툴별 문구 정확).
# core 수정 후 항상 실행하고 생성물까지 함께 커밋한다. CI 가 drift 를 검사한다.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# SKILL.md 의 {{PLACEHOLDER}} 를 어댑터별 값으로 치환 (sed 구분자 | — 값에 / 포함 대비)
render() { # $1=src  $2=dst   (env: AGENT RULES_FILE HANDOFF DEEP_RECOVERY PATH_NOTE PERSONAL_TIER_NOTE PROJECT_DIR_ARG)
  sed -e "s|{{AGENT}}|$AGENT|g" \
      -e "s|{{RULES_FILE}}|$RULES_FILE|g" \
      -e "s|{{HANDOFF}}|$HANDOFF|g" \
      -e "s|{{DEEP_RECOVERY}}|$DEEP_RECOVERY|g" \
      -e "s|{{PATH_NOTE}}|$PATH_NOTE|g" \
      -e "s|{{PERSONAL_TIER_NOTE}}|$PERSONAL_TIER_NOTE|g" \
      -e "s|{{PROJECT_DIR_ARG}}|$PROJECT_DIR_ARG|g" \
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
PERSONAL_TIER_NOTE=''   # Claude: auto-memory 가 개인 tier 를 자동 로드 — 주의 불필요
PROJECT_DIR_ARG=''   # Claude: CLAUDE_PROJECT_DIR env 로 자동 해석 — 명령에 인자 불필요
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
{
  printf '%s\n' '{'
  printf '%s\n' '  "hooks": {'
  printf '%s\n' '    "PreToolUse": ['
  printf '%s\n' '      { "matcher": "Edit|Write|MultiEdit", "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/memory-search.py\"" } ] }'
  printf '%s\n' '    ],'
  printf '%s\n' '    "PostToolUse": ['
  printf '%s\n' '      { "matcher": "Edit|Write|MultiEdit", "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/reflection.py\"" } ] },'
  printf '%s\n' '      { "matcher": "Bash", "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/pr-merge-reflect.py\"" } ] }'
  printf '%s\n' '    ],'
  printf '%s\n' '    "SessionStart": ['
  printf '%s\n' '      { "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/pr-merge-reflect.py\"" } ] }'
  printf '%s\n' '    ],'
  printf '%s\n' '    "UserPromptSubmit": ['
  printf '%s\n' '      { "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/pr-merge-reflect.py\"" } ] }'
  printf '%s\n' '    ]'
  printf '%s\n' '  }'
  printf '%s\n' '}'
} > plugins/harness/hooks/hooks.json

# ── Codex 어댑터: codex/ (skill-only plugin) ────────────────────
# 스크립트는 스킬 폴더에 번들(scripts/) — bin PATH 가정 회피(Codex 미검증 영역).
rm -rf codex/skills codex/bin
AGENT=codex; RULES_FILE=AGENTS.md; HANDOFF='python3 scripts/handoff.py'
DEEP_RECOVERY='`~/.codex/sessions` 의 최근 세션 로그'
# Codex: 위 경로는 이 SKILL.md 가 있는 스킬 폴더 기준 상대경로 — 스킬 폴더로 cd 해 실행하되,
# 스크립트가 cwd 기준 git 루트로 프로젝트를 찾으므로(스킬 폴더=플러그인 캐시는 사용자 repo 밖일 수 있음)
# 반드시 --project-dir 로 사용자 프로젝트를 명시하게 한다. (OpenAI 번들 스킬의 "cd to plugin root +
# 절대경로 인자" 관례와 동일. 이 인자 없으면 핸드오프가 엉뚱한 위치에 저장되는 버그 — 이슈 #3.)
PATH_NOTE='> ⚠️ 위 명령의 `scripts/handoff.py` 는 **이 SKILL.md 가 있는 스킬 디렉토리 기준 상대경로**다. 그 스킬 폴더로 cd 해서 실행하되, 위 예시의 `--project-dir` 를 **지금 작업 중인 사용자 프로젝트의 실제 절대경로로 바꿔서** 넘겨라 — 스킬 폴더는 플러그인 캐시라 사용자 repo 밖일 수 있어, 이 인자 없이는 git 루트 탐지가 빗나가 핸드오프가 엉뚱한 위치에 저장된다.'
# Codex 명령 예시에 실제로 --project-dir 를 넣는다(각주만으론 복붙 시 누락 — 리뷰 지적). 후행 공백 유지.
PROJECT_DIR_ARG='--project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>" '
# Codex: 개인 tier 경로는 Claude auto-memory — Codex 는 다음 세션에서 자동 로드하지 못함
PERSONAL_TIER_NOTE='  > ⚠️ Codex 세션 주의: 위 개인 tier 경로는 **Claude auto-memory** 라 Claude 만 다음 세션에서 자동 로드한다. Codex 는 재로딩 메커니즘이 없으므로, Codex 에서도 필요할 항목이면 공유 tier(커밋 메모리 + INDEX.md)로 저장을 우선 검토하라.'
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
