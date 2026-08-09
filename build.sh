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
      -e "s|{{FW_FROM_DEFAULT}}|$FW_FROM_DEFAULT|g" \
      -e "s|{{STALE}}|$STALE|g" \
      -e "s|{{STALE_NOTE}}|$STALE_NOTE|g" \
      -e "s|{{MERGE_CLEANUP}}|$MERGE_CLEANUP|g" \
      -e "s|{{MERGE_CLEANUP_EXAMPLE}}|$MERGE_CLEANUP_EXAMPLE|g" \
      -e "s|{{MERGE_CLEANUP_NOTE}}|$MERGE_CLEANUP_NOTE|g" \
      -e "s|{{PRETTIER_GUARD}}|$PRETTIER_GUARD|g" \
      -e "s|{{PRETTIER_GUARD_EXAMPLE}}|$PRETTIER_GUARD_EXAMPLE|g" \
      -e "s|{{PRETTIER_GUARD_NOTE}}|$PRETTIER_GUARD_NOTE|g" \
      -e "s|{{REVIEW_LEDGER_EXAMPLE}}|$REVIEW_LEDGER_EXAMPLE|g" \
      -e "s|{{REVIEW_LEDGER_NOTE}}|$REVIEW_LEDGER_NOTE|g" \
      -e "s|{{VERIFY_REGRESSION_EXAMPLE}}|$VERIFY_REGRESSION_EXAMPLE|g" \
      -e "s|{{VERIFY_REGRESSION_NOTE}}|$VERIFY_REGRESSION_NOTE|g" \
      "$1" > "$2"
}

SKILLS=$(cd core/skills && ls -d */ | sed 's#/##')

# ── Claude 어댑터: plugins/harness ──────────────────────────────
# 스크립트는 bin/ 공유(플러그인 활성 시 PATH 등록 — 검증됨).
rm -rf plugins/harness/skills plugins/harness/bin plugins/harness/hooks
mkdir -p plugins/harness/bin
cp core/scripts/handoff.py plugins/harness/bin/agent-handoff
chmod +x plugins/harness/bin/agent-handoff
# repo_identity: agent-handoff 가 dirname(__file__)=bin/ 에서 import 한다(co-locate 규약).
cp core/scripts/repo_identity.py plugins/harness/bin/repo_identity.py
# stale detector: orchestrator(stale.py→agent-stale) + A/B 헬퍼를 bin/ 에 co-locate.
# agent-stale 이 dirname(__file__)=bin/ 에서 stale_collect·stale_resolve 를 import 한다.
cp core/scripts/stale.py plugins/harness/bin/agent-stale
cp core/scripts/stale_collect.py plugins/harness/bin/stale_collect.py
cp core/scripts/stale_resolve.py plugins/harness/bin/stale_resolve.py
cp core/scripts/merge_cleanup.py plugins/harness/bin/agent-merge-cleanup
cp core/scripts/prettier_guard.py plugins/harness/bin/agent-prettier-guard
cp core/scripts/review_ledger.py plugins/harness/bin/agent-review-ledger
cp core/scripts/verify_regression.py plugins/harness/bin/agent-verify-regression
chmod +x plugins/harness/bin/agent-stale
chmod +x plugins/harness/bin/agent-merge-cleanup
chmod +x plugins/harness/bin/agent-prettier-guard
chmod +x plugins/harness/bin/agent-review-ledger
chmod +x plugins/harness/bin/agent-verify-regression
AGENT=claude; RULES_FILE=CLAUDE.md; HANDOFF=agent-handoff
STALE=agent-stale; STALE_NOTE=''   # Claude: bin/ 이 PATH 등록 — 경로 주석 불필요
MERGE_CLEANUP=agent-merge-cleanup; MERGE_CLEANUP_NOTE=''
MERGE_CLEANUP_EXAMPLE='agent-merge-cleanup'
PRETTIER_GUARD=agent-prettier-guard; PRETTIER_GUARD_NOTE=''
PRETTIER_GUARD_EXAMPLE='agent-prettier-guard'
REVIEW_LEDGER_EXAMPLE='agent-review-ledger'
REVIEW_LEDGER_NOTE=''
VERIFY_REGRESSION_EXAMPLE='agent-verify-regression'
VERIFY_REGRESSION_NOTE=''
DEEP_RECOVERY='`/fw-claude` 또는 `/continue-claude`'
PATH_NOTE=''   # Claude: bin/ 이 PATH 등록되어 cwd 무관
PERSONAL_TIER_NOTE=''   # Claude: auto-memory 가 개인 tier 를 자동 로드 — 주의 불필요
PROJECT_DIR_ARG=''   # Claude: CLAUDE_PROJECT_DIR env 로 자동 해석 — 명령에 인자 불필요
FW_FROM_DEFAULT='codex'   # Claude fw 는 반대 툴(codex) 로그를 복원 — 현재 Claude 세션 자기선택 방지
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
# repo_identity 는 core/scripts 에 있지만 pr-merge-reflect 훅도 import 한다 → hooks/ 에도 co-locate.
cp core/scripts/repo_identity.py plugins/harness/hooks/repo_identity.py
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
  printf '%s\n' '      { "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/project-memory-index.py\"" } ] },'
  printf '%s\n' '      { "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/pr-merge-reflect.py\"" } ] }'
  printf '%s\n' '    ],'
  printf '%s\n' '    "UserPromptSubmit": ['
  printf '%s\n' '      { "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/pr-merge-reflect.py\"" } ] }'
  printf '%s\n' '    ]'
  printf '%s\n' '  }'
  printf '%s\n' '}'
} > plugins/harness/hooks/hooks.json

# ── Codex 어댑터: plugins/codex/ (skill-only plugin) ────────────
# canonical 관례(plugins/<name>) 정렬 — OpenAI 마켓·Claude 어댑터와 동일 위치(이슈 #4).
# 스크립트는 스킬 폴더에 번들(scripts/) — bin PATH 가정 회피(Codex 미검증 영역).
rm -rf plugins/codex/skills plugins/codex/bin
AGENT=codex; RULES_FILE=AGENTS.md; HANDOFF='python3 scripts/handoff.py'
STALE='python3 scripts/stale.py'
STALE_NOTE='> ⚠️ 위 `scripts/stale.py` 는 이 SKILL.md 가 있는 스킬 디렉토리 기준 상대경로다. 그 스킬 폴더로 cd 한 뒤 실행하라. (`--repo` 로 대상 repo 를 명시하므로 cwd/git 루트에는 의존하지 않지만, 명령의 `scripts/` 경로 때문에 스킬 폴더에서 실행해야 한다.)'
MERGE_CLEANUP='python3 scripts/merge_cleanup.py'
MERGE_CLEANUP_NOTE='> ⚠️ 위 `scripts/merge_cleanup.py` 는 이 SKILL.md 가 있는 스킬 디렉토리 기준 상대경로다. 그 스킬 폴더로 cd 한 뒤 실행하되, `--project-dir` 에 지금 작업 중인 사용자 프로젝트의 실제 절대경로를 넘겨라. 이 인자 없이는 플러그인 캐시를 검사할 수 있다.'
MERGE_CLEANUP_EXAMPLE='python3 scripts/merge_cleanup.py --project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>"'
PRETTIER_GUARD='python3 scripts/prettier_guard.py'
PRETTIER_GUARD_NOTE='> ⚠️ 위 `scripts/prettier_guard.py` 는 이 SKILL.md 가 있는 스킬 디렉토리 기준 상대경로다. 그 스킬 폴더로 cd 한 뒤 실행하되, `--project-dir` 에 지금 작업 중인 사용자 프로젝트의 실제 절대경로를 넘겨라. 이 인자 없이는 플러그인 캐시를 검사할 수 있다.'
PRETTIER_GUARD_EXAMPLE='python3 scripts/prettier_guard.py --project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>"'
REVIEW_LEDGER_EXAMPLE='python3 scripts/review_ledger.py --project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>"'
REVIEW_LEDGER_NOTE='> ⚠️ `scripts/review_ledger.py` 는 이 스킬 폴더 기준 상대경로다. 스킬 폴더에서 실행하고 `--project-dir` 에 사용자 프로젝트 절대경로를 넘겨라.'
VERIFY_REGRESSION_EXAMPLE='python3 scripts/verify_regression.py --project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>"'
VERIFY_REGRESSION_NOTE='> ⚠️ `scripts/verify_regression.py` 는 이 스킬 폴더 기준 상대경로다. 스킬 폴더에서 실행하고 `--project-dir` 에 사용자 프로젝트 절대경로를 넘겨라.'
DEEP_RECOVERY='`~/.codex/sessions` 의 최근 세션 로그'
# Codex: 위 경로는 이 SKILL.md 가 있는 스킬 폴더 기준 상대경로 — 스킬 폴더로 cd 해 실행하되,
# 스크립트가 cwd 기준 git 루트로 프로젝트를 찾으므로(스킬 폴더=플러그인 캐시는 사용자 repo 밖일 수 있음)
# 반드시 --project-dir 로 사용자 프로젝트를 명시하게 한다. (OpenAI 번들 스킬의 "cd to plugin root +
# 절대경로 인자" 관례와 동일. 이 인자 없으면 핸드오프가 엉뚱한 위치에 저장되는 버그 — 이슈 #3.)
PATH_NOTE='> ⚠️ 위 명령의 `scripts/handoff.py` 는 **이 SKILL.md 가 있는 스킬 디렉토리 기준 상대경로**다. 그 스킬 폴더로 cd 해서 실행하되, 위 예시의 `--project-dir` 를 **지금 작업 중인 사용자 프로젝트의 실제 절대경로로 바꿔서** 넘겨라 — 스킬 폴더는 플러그인 캐시라 사용자 repo 밖일 수 있어, 이 인자 없이는 git 루트 탐지가 빗나가 핸드오프가 엉뚱한 위치에 저장된다.'
# Codex 명령 예시에 실제로 --project-dir 를 넣는다(각주만으론 복붙 시 누락 — 리뷰 지적). 후행 공백 유지.
PROJECT_DIR_ARG='--project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>" '
FW_FROM_DEFAULT='claude'   # Codex fw 는 반대 툴(claude) 로그를 복원 — 현재 Codex 세션 자기선택 방지
# Codex: 개인 tier 경로는 Claude auto-memory — Codex 는 다음 세션에서 자동 로드하지 못함
PERSONAL_TIER_NOTE='  > ⚠️ Codex 세션 주의: 위 개인 tier 경로는 **Claude auto-memory** 라 Claude 만 다음 세션에서 자동 로드한다. Codex 는 재로딩 메커니즘이 없으므로, Codex 에서도 필요할 항목이면 공유 tier(커밋 메모리 + INDEX.md)로 저장을 우선 검토하라.'
for s in $SKILLS; do
  mkdir -p "plugins/codex/skills/$s/scripts"
  if [ "$s" != "merge-cleanup" ] && [ "$s" != "prettier-guard" ]; then
    cp core/scripts/handoff.py "plugins/codex/skills/$s/scripts/handoff.py"
    # handoff.py 가 같은 폴더에서 import 한다 — 번들되는 곳마다 함께 둔다.
    cp core/scripts/repo_identity.py "plugins/codex/skills/$s/scripts/repo_identity.py"
  fi
  render "core/skills/$s/SKILL.md" "plugins/codex/skills/$s/SKILL.md"
done
# stale-scan 스킬만 stale 3-스크립트를 번들(그 스킬만 씀). stale.py 가 같은 폴더에서
# stale_collect·stale_resolve 를 import 한다.
cp core/scripts/stale.py core/scripts/stale_collect.py core/scripts/stale_resolve.py \
   plugins/codex/skills/stale-scan/scripts/
cp core/scripts/merge_cleanup.py plugins/codex/skills/merge-cleanup/scripts/
cp core/scripts/prettier_guard.py plugins/codex/skills/prettier-guard/scripts/
cp core/scripts/review_ledger.py plugins/codex/skills/review-ledger/scripts/
cp core/scripts/verify_regression.py plugins/codex/skills/verify-regression/scripts/

# ── Codex 훅 (스파이크: project-memory-index 하나만) ────────────
# 검증된 사실(codex 0.145.0): 플러그인 매니페스트의 "hooks" 키가 hooks.json 을 가리키고,
# Codex 가 **`CLAUDE_PLUGIN_ROOT` 를 호환 별칭으로 세팅**해 준다 → hooks.json 은 Claude 와 공용 형식.
# 단 `CLAUDE_PROJECT_DIR` 은 안 준다 — 훅 스크립트가 입력 JSON 의 `cwd` 로 프로젝트를 찾는다.
# ⚠️ 상대경로 command 는 실패한다(프로세스 cwd = 사용자 프로젝트). 반드시 ${CLAUDE_PLUGIN_ROOT} 기준.
# ⚠️ 사용자가 훅 신뢰를 등록하기 전까지 Codex 는 훅을 **조용히 무시**한다(에러 없음).
rm -rf plugins/codex/hooks
mkdir -p plugins/codex/hooks
cp core/hooks/project-memory-index.py plugins/codex/hooks/
chmod +x plugins/codex/hooks/*.py
{
  printf '%s\n' '{'
  printf '%s\n' '  "hooks": {'
  printf '%s\n' '    "SessionStart": ['
  printf '%s\n' '      { "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/project-memory-index.py\"" } ] }'
  printf '%s\n' '    ]'
  printf '%s\n' '  }'
  printf '%s\n' '}'
} > plugins/codex/hooks/hooks.json

# 렌더 후 미치환 placeholder 가드 — SKILL.md 만 검사한다.
# (번들된 스크립트는 검사 제외: stale_resolve.py 의 GraphQL f-string `{{` 처럼
#  정당한 이중중괄호가 있어 placeholder 로 오탐된다. placeholder 는 SKILL.md 만의 개념.)
if grep -rl --include='SKILL.md' '{{' plugins/harness/skills plugins/codex/skills 2>/dev/null | grep -q .; then
  echo "ERROR: 미치환 placeholder 남음"; grep -rn --include='SKILL.md' '{{' plugins/harness/skills plugins/codex/skills; exit 1
fi
echo "빌드 완료: core → Claude(plugins/harness, bin PATH) + Codex(plugins/codex, skill별 scripts 번들)"
