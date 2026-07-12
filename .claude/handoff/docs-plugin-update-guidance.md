# 작업 핸드오프 — docs/plugin-update-guidance

> 갱신: 2026-07-12T22:26:59+08:00 · 에이전트: codex · 머신: Miyoungs-MacBook-Pro.local
> ⚠️ 이 파일은 **커밋됨**. 이어받는 사람/툴은 먼저 이걸 읽고 **현재 git 상태와 대조**한 뒤 진행하세요.
> transcript 만 믿지 말 것 — git 사실이 우선입니다.

## 요약
PR #7: Codex/Claude 플러그인 설치·업데이트 UX 문서화. README에는 사용자 명령, AGENTS에는 릴리스 운영 규칙을 추가.

## 완료한 것
- README.md에 Codex 설치 명령과 업데이트 절차(marketplace upgrade + remove/add) 추가
- AGENTS.md에 로컬 dogfooding과 사용자 릴리스 분리, 버전 bump, Codex 캐시 갱신 규칙 추가
- Claude Code 리뷰 수행: command accuracy 기준 actionable finding 없음
- draft PR #7 생성: https://github.com/foxyberry/agent-harness/pull/7

## 남은 것 / 다음 액션
- PR #7 내용을 최종 확인
- 필요하면 draft 해제 후 merge
- 릴리스 운영을 실제로 적용할 때 codex/.codex-plugin/plugin.json 버전 bump 정책을 별도 PR로 정리

## 검증 상태
- git diff --check 통과
- Claude Code 리뷰: no actionable findings
- gh pr view #7 확인: OPEN draft PR

---
<!-- handoff:auto -->
## Git 사실 (자동 수집 @ 2026-07-12T22:26:59+08:00)

- 브랜치: `docs/plugin-update-guidance`
- origin/main 대비 커밋:
```
e4d5add docs: document plugin update workflow
```
- 변경 파일 (status -sb):
```
## docs/plugin-update-guidance...origin/docs/plugin-update-guidance
```
- diff --stat (unstaged):
```
(없음)
```
- diff --stat (staged):
```
(없음)
```
- 열린 PR: #7 docs: document plugin update workflow — https://github.com/foxyberry/agent-harness/pull/7
