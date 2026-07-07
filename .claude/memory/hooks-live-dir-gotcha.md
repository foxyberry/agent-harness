---
name: hooks-live-dir-gotcha
description: 플러그인이 작업 repo 직접 참조(dev 설치) — 훅 파일 삭제/개명 시 실행 중 다른 세션 Bash 블록
type: project
---

agent-harness 플러그인은 `${CLAUDE_PLUGIN_ROOT}` = `~/Repository/agent-harness/plugins/harness`
인 **live-dir dev 설치**다(캐시 복사본 아님). `plugins/harness/hooks/`(=`core/hooks/`) 아래 파일을
편집·삭제하면 **다른 프로젝트에서 돌고 있는 모든 Claude 세션**에 다음 훅 발화 때 즉시 반영된다.

**Why:** 세션은 시작 시 hooks.json 을 메모리에 로드한다. 참조된 훅 스크립트를 지우면 이미 떠 있는
세션은 옛 설정으로 없는 파일을 실행 → `python3` exit 2 → Claude Code 가 PreToolUse exit 2 를
"차단"으로 해석 → 그 세션의 **모든 Bash 가 막힌다**. (2026-07-07 ket-woojin 에서 pre-push-guard 삭제로 발생.)

**How to apply:** core/hooks 훅을 삭제·개명 전에 (1) 다른 세션 블록 가능성을 사용자에게 알리고,
(2) 즉시 언블록이 필요하면 그 자리에 exit-0 no-op shim 을 남기거나, (3) 영향받은 세션은 재시작해야
최신 hooks.json 이 로드됨을 안내한다. 훅은 파일 **부재**까지는 fail-open 못 한다(인터프리터가
스크립트 열기 전에 죽음). 관련: [[engine-data-separation]]
