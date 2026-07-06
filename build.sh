#!/usr/bin/env bash
# core/ (정본) → 각 툴 어댑터로 복사 생성. symlink 대신 복사(크로스플랫폼·외부배포 안전).
# core 수정 후 항상 실행하고 생성물까지 함께 커밋한다.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ── Claude 어댑터: plugins/harness ──────────────────────────────
rm -rf plugins/harness/skills plugins/harness/bin
mkdir -p plugins/harness/skills plugins/harness/bin
cp -R core/skills/. plugins/harness/skills/
cp core/scripts/handoff.py plugins/harness/bin/agent-handoff   # 플러그인 활성 시 PATH 등록(bin/)
chmod +x plugins/harness/bin/agent-handoff

# ── Codex 어댑터: codex/ (skill-only plugin) ────────────────────
# 매니페스트(.codex-plugin/plugin.json)는 정적 유지, skills/ 와 공유 스크립트만 core 에서 생성.
rm -rf codex/skills codex/bin
mkdir -p codex/skills codex/bin
cp -R core/skills/. codex/skills/
cp core/scripts/handoff.py codex/bin/agent-handoff
chmod +x codex/bin/agent-handoff

echo "빌드 완료: core → plugins/harness (Claude) + codex/ (Codex)"
