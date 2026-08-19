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
      -e "s|{{COMPACT}}|$COMPACT|g" \
      -e "s|{{DEEP_RECOVERY}}|$DEEP_RECOVERY|g" \
      -e "s|{{PATH_NOTE}}|$PATH_NOTE|g" \
      -e "s|{{PERSONAL_TIER_NOTE}}|$PERSONAL_TIER_NOTE|g" \
      -e "s|{{PROJECT_DIR_ARG}}|$PROJECT_DIR_ARG|g" \
      -e "s|{{FW_FROM_DEFAULT}}|$FW_FROM_DEFAULT|g" \
      "$1" > "$2"
}

# 훅 command 는 **스크립트가 없으면 아무것도 안 하고 exit 0** 이어야 한다.
# python3 은 파일을 못 열면 exit 2 를 내는데, 훅 계약에서 2 는 "이 도구 호출을 차단" 이다.
# 그래서 플러그인이 업데이트되어 옛 버전 캐시 디렉터리가 지워지면, 그 경로를 물고 있던
# 세션의 셸 명령이 전부 막힌다 — 파이썬의 "파일 못 열어"가 그대로 "거부해"로 전달된다(#107).
#
# ⚠️ `if` 형태여야 한다. `python3 "$p" || exit 0` 도 파일 없음은 막지만 **훅이 의도적으로 낸
# exit 2 까지 삼켜서** 앞으로 만들 어떤 차단 훅도 조용히 무력화된다. `if` 는 1·2 를 그대로
# 통과시키므로 어느 훅이 차단하는지 감사할 필요가 없다.
hook_command() {  # $1 = 훅 스크립트 파일명 → JSON 문자열용 이스케이프된 셸 명령
  printf 'p=\\"${CLAUDE_PLUGIN_ROOT}/hooks/%s\\"; if [ -f \\"$p\\" ]; then python3 \\"$p\\"; fi' "$1"
}

SKILLS=$(cd core/skills && ls -d */ | sed 's#/##')

# ── Claude 어댑터: plugins/harness ──────────────────────────────
# 스크립트는 bin/ 공유(플러그인 활성 시 PATH 등록 — 검증됨).
rm -rf plugins/harness/skills plugins/harness/bin plugins/harness/hooks
mkdir -p plugins/harness/bin
cp core/scripts/handoff.py plugins/harness/bin/agent-handoff
# repo_identity: agent-handoff 가 dirname(__file__)=bin/ 에서 import 한다(co-locate 규약).
cp core/scripts/repo_identity.py plugins/harness/bin/repo_identity.py
# 회고 스킬이 과거 세션을 후보로 쓸 때 압축본이 필요하다(원본은 수 MB). 훅에도 같은 파일이
# 있지만 스킬은 hooks/ 를 참조하지 않는다 — repo_identity 와 같은 co-locate 규약.
cp core/hooks/compact_transcript.py plugins/harness/bin/compact_transcript.py
# ⚠️ chmod 는 **cp 다음**이다. 없는 파일에 chmod 하면 build.sh 가 거기서 멈춘다.
chmod +x plugins/harness/bin/agent-handoff plugins/harness/bin/compact_transcript.py
AGENT=claude; RULES_FILE=CLAUDE.md; HANDOFF=agent-handoff; COMPACT=compact_transcript.py
DEEP_RECOVERY='`/fw --from claude` 또는 `/fw-both`'   # 실제 존재하는 명령만 (없는 이름을 안내하면 손 탐색을 부른다 — 이슈 #95)
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
# hook_io: 편집 훅(memory-search·reflection)이 입력 정규화·출력 방출에 쓴다. 같은 규약으로 co-locate.
cp core/scripts/hook_io.py plugins/harness/hooks/hook_io.py
chmod +x plugins/harness/hooks/*.py
{
  printf '%s\n' '{'
  printf '%s\n' '  "hooks": {'
  printf '%s\n' '    "PreToolUse": ['
  printf '      { "matcher": "Edit|Write|MultiEdit|Bash", "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command memory-search.py)"
  printf '%s\n' '    ],'
  printf '%s\n' '    "PostToolUse": ['
  printf '      { "matcher": "Edit|Write|MultiEdit", "hooks": [ { "type": "command", "command": "%s" } ] },\n' "$(hook_command reflection.py)"
  printf '      { "matcher": "Bash", "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command pr-merge-reflect.py)"
  printf '%s\n' '    ],'
  printf '%s\n' '    "SessionStart": ['
  printf '      { "hooks": [ { "type": "command", "command": "%s" } ] },\n' "$(hook_command project-memory-index.py)"
  printf '      { "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command pr-merge-reflect.py)"
  printf '%s\n' '    ],'
  printf '%s\n' '    "UserPromptSubmit": ['
  printf '      { "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command pr-merge-reflect.py)"
  printf '%s\n' '    ]'
  printf '%s\n' '  }'
  printf '%s\n' '}'
} > plugins/harness/hooks/hooks.json

# ── Codex 어댑터: plugins/codex/ (skill-only plugin) ────────────
# canonical 관례(plugins/<name>) 정렬 — OpenAI 마켓·Claude 어댑터와 동일 위치(이슈 #4).
# 스크립트는 스킬 폴더에 번들(scripts/) — bin PATH 가정 회피(Codex 미검증 영역).
rm -rf plugins/codex/skills plugins/codex/bin
AGENT=codex; RULES_FILE=AGENTS.md; HANDOFF='python3 scripts/handoff.py'
COMPACT='python3 scripts/compact_transcript.py'
# 예전 값은 "`~/.codex/sessions` 의 최근 세션 로그" 였다 — 폴더를 직접 뒤지라는 안내다.
# 손 탐색에는 프로젝트 스코핑이 없어서 남의 프로젝트 세션을 집을 수 있다(이슈 #95).
DEEP_RECOVERY='`/fw --from codex` 또는 `/fw-both`'
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
  # 남은 스킬은 전부 handoff.py 를 쓴다(예외였던 merge-cleanup·prettier-guard 는 개인 스코프로 이동).
  cp core/scripts/handoff.py "plugins/codex/skills/$s/scripts/handoff.py"
  # handoff.py 가 같은 폴더에서 import 한다 — 번들되는 곳마다 함께 둔다.
  cp core/scripts/repo_identity.py "plugins/codex/skills/$s/scripts/repo_identity.py"
  cp core/hooks/compact_transcript.py "plugins/codex/skills/$s/scripts/compact_transcript.py"
  render "core/skills/$s/SKILL.md" "plugins/codex/skills/$s/SKILL.md"
done

# ── Codex 훅 ───────────────────────────────────────────────────
# 검증된 사실(codex 0.145.0): 플러그인 매니페스트의 "hooks" 키가 hooks.json 을 가리키고,
# Codex 가 **`CLAUDE_PLUGIN_ROOT` 를 호환 별칭으로 세팅**해 준다 → hooks.json 은 Claude 와 공용 형식.
# 단 `CLAUDE_PROJECT_DIR` 은 안 준다 — 훅 스크립트가 입력 JSON 의 `cwd` 로 프로젝트를 찾는다.
# ⚠️ 상대경로 command 는 실패한다(프로세스 cwd = 사용자 프로젝트). 반드시 ${CLAUDE_PLUGIN_ROOT} 기준.
# ⚠️ 사용자가 훅 신뢰를 등록하기 전까지 Codex 는 훅을 **조용히 무시**한다(에러 없음).
# matcher 는 **실측된 도구 이름**을 쓴다: 파일 편집=`apply_patch`, 셸=`Bash`(0.145.0).
# rollout 로그에 보이는 `exec` 는 tool_use_id 접두사지 도구 이름이 아니다 — 로그로 정하지 말 것.
# `Edit|Write` 도 matcher 로 받아준다고 문서에 있으나, 실측된 이름만 쓴다.
# pr-merge-reflect 는 아직 안 올린다 — LLM 잡·seen 캐시가 붙어 있고 Codex 세션에서
# Codex 회고를 또 띄우는 중복 정리가 선행이다(이슈 #85 3단계).
rm -rf plugins/codex/hooks
mkdir -p plugins/codex/hooks
cp core/hooks/project-memory-index.py core/hooks/memory-search.py core/hooks/reflection.py \
   plugins/codex/hooks/
# 편집 훅이 dirname(__file__) 에서 import 한다 — 번들되는 곳마다 함께 둔다.
cp core/scripts/hook_io.py plugins/codex/hooks/hook_io.py
chmod +x plugins/codex/hooks/*.py
{
  printf '%s\n' '{'
  printf '%s\n' '  "hooks": {'
  printf '%s\n' '    "PreToolUse": ['
  printf '      { "matcher": "apply_patch|Bash", "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command memory-search.py)"
  printf '%s\n' '    ],'
  printf '%s\n' '    "PostToolUse": ['
  printf '      { "matcher": "apply_patch", "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command reflection.py)"
  printf '%s\n' '    ],'
  printf '%s\n' '    "SessionStart": ['
  printf '      { "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command project-memory-index.py)"
  printf '%s\n' '    ]'
  printf '%s\n' '  }'
  printf '%s\n' '}'
} > plugins/codex/hooks/hooks.json

# 렌더 후 미치환 placeholder 가드 — SKILL.md 만 검사한다.
#  정당한 이중중괄호가 있어 placeholder 로 오탐된다. placeholder 는 SKILL.md 만의 개념.)
if grep -rl --include='SKILL.md' '{{' plugins/harness/skills plugins/codex/skills 2>/dev/null | grep -q .; then
  echo "ERROR: 미치환 placeholder 남음"; grep -rn --include='SKILL.md' '{{' plugins/harness/skills plugins/codex/skills; exit 1
fi
echo "빌드 완료: core → Claude(plugins/harness, bin PATH) + Codex(plugins/codex, skill별 scripts 번들)"
