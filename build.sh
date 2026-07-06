#!/usr/bin/env bash
# core/ (정본 템플릿) → 각 툴 어댑터로 렌더링 생성. symlink 대신 렌더(크로스플랫폼·툴별 문구 정확).
# core 수정 후 항상 실행하고 생성물까지 함께 커밋한다. CI 가 drift 를 검사한다.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# SKILL.md 의 {{PLACEHOLDER}} 를 어댑터별 값으로 치환 (sed 구분자 | — 값에 / 포함 대비)
render() { # $1=src  $2=dst   (env: AGENT RULES_FILE HANDOFF DEEP_RECOVERY)
  sed -e "s|{{AGENT}}|$AGENT|g" \
      -e "s|{{RULES_FILE}}|$RULES_FILE|g" \
      -e "s|{{HANDOFF}}|$HANDOFF|g" \
      -e "s|{{DEEP_RECOVERY}}|$DEEP_RECOVERY|g" \
      "$1" > "$2"
}

SKILLS=$(cd core/skills && ls -d */ | sed 's#/##')

# ── Claude 어댑터: plugins/harness ──────────────────────────────
# 스크립트는 bin/ 공유(플러그인 활성 시 PATH 등록 — 검증됨).
rm -rf plugins/harness/skills plugins/harness/bin
mkdir -p plugins/harness/bin
cp core/scripts/handoff.py plugins/harness/bin/agent-handoff
chmod +x plugins/harness/bin/agent-handoff
AGENT=claude; RULES_FILE=CLAUDE.md; HANDOFF=agent-handoff
DEEP_RECOVERY='`/fw-claude` 또는 `/continue-claude`'
for s in $SKILLS; do
  mkdir -p "plugins/harness/skills/$s"
  render "core/skills/$s/SKILL.md" "plugins/harness/skills/$s/SKILL.md"
done

# ── Codex 어댑터: codex/ (skill-only plugin) ────────────────────
# 스크립트는 스킬 폴더에 번들(scripts/) — bin PATH 가정 회피(Codex 미검증 영역).
rm -rf codex/skills codex/bin
AGENT=codex; RULES_FILE=AGENTS.md; HANDOFF='python3 scripts/handoff.py'
DEEP_RECOVERY='`~/.codex/sessions` 의 최근 세션 로그'
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
