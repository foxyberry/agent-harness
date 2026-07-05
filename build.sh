#!/usr/bin/env bash
# core/ (정본) → 각 어댑터로 복사 생성. symlink 대신 복사(크로스플랫폼·외부배포 안전).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# --- Claude 어댑터: plugins/harness ---
rm -rf plugins/harness/skills plugins/harness/bin
mkdir -p plugins/harness/skills plugins/harness/bin
cp -R core/skills/. plugins/harness/skills/
# 공유 실행파일: core 스크립트 → bin/agent-handoff (플러그인 활성 시 PATH 등록)
cp core/scripts/handoff.py plugins/harness/bin/agent-handoff
chmod +x plugins/harness/bin/agent-handoff

echo "빌드 완료: core → plugins/harness (Claude)"
# TODO(codex adapter): 검증(#1) 후 core → codex/ 생성 추가
