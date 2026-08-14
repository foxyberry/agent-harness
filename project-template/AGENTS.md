# AGENTS.md — <프로젝트명>

이 파일이 에이전트 지침의 **정본(single source of truth)** 이다.
Codex 는 이 파일을 직접 읽고, Claude Code 는 `CLAUDE.md` 가 이 파일을 `@import` 한다.
(둘을 따로 관리하지 말 것 — 규칙은 항상 여기에만 쓴다.)

## 프로젝트 개요

<이 repo 가 무엇인지 한두 줄. 스택·주요 디렉토리.>

## 작업 규칙

- main 직접 푸시 금지 — 브랜치 + PR 로 진행.
- <커밋 승인 규칙: 예) 커밋 전 사용자에게 확인>
- <빌드/테스트 명령: 예) ./gradlew test>

## PR 설명 규칙

- 모든 PR 제목은 conventional type으로 시작한다. 예: `feat(scope): 설명`, `docs: 설명`.
  브랜치 이름이나 이모지를 제목 앞에 붙이지 않는다. GitHub 자동 revert 제목은 예외다.
- `feat`, `fix`, `refactor`, `perf` PR은 무엇을 바꿨는지와 실제로 어떻게 동작하는지를
  한국어·영어로 각각 설명한다.
- PR 본문에는 `구현 내용 (KR)`, `구현 로직 (KR)`, `Implementation Summary (EN)`,
  `Implementation Logic (EN)` 네 섹션을 모두 작성한다.
- 구현 로직에는 핵심 실행 순서, 조건 분기, 데이터 흐름, 실패·예외 처리를 쉬운 말로 적는다.
  변경 파일 이름이나 함수 이름만 나열하는 것은 구현 설명으로 보지 않는다.
- `.github/workflows/pr-body-check.yml`이 네 섹션의 존재와 최소 내용을 검사한다.

## 메모리 (agent-harness)

- 공유 메모리는 `.claude/memory/` 에 **커밋**된다. 목록은 `.claude/memory/INDEX.md`.
- Claude 플러그인은 세션 시작 시 `INDEX.md` 를 자동으로 주입한다. Codex 는 아직 훅 배포가 없어
  작업 시작 시 이 인덱스를 직접 읽는 것을 기본 규칙으로 둔다.
- 훅 데이터: `routes.json`(편집 파일·셸 명령→메모리 주입), `reflection-rules.json`(품질 경고 정규식),
  `reflect-skip.json`(회고 산출물 PR skip rule).
  이 프로젝트 언어·규칙에 맞게 고쳐 쓴다 — 없으면 훅은 조용히 no-op.
- governance: 자동 회고 초안은 `_pending/` 에만 쌓이고, `/memory-update` 로
  **사람 승인 후** 승격된다. 민감정보(키·토큰·내부 URL)는 메모리·핸드오프에 금지.
- `.claude/.cache/` 는 훅·스킬의 로컬 상태와 로그이며 Git에 커밋하지 않는다.
- 메모리에는 오래 유지할 결정·제약·패턴만 둔다. WIP·진행 중 PR·다음 액션은 실제 전환
  시점의 `/handoff-save` 로만 인계하고, 줄 수·테스트 수처럼 다시 구할 수 있는 값은 저장하지 않는다.

## 핸드오프

- 세션·툴(Codex↔Claude)·머신·사람을 바꾸기 전 `/handoff-save` — `.claude/handoff/<브랜치>.md` 로 커밋.
- 이어받을 때 `/handoff-load` — 커밋된 핸드오프 1순위, 현재 git 상태가 항상 우선.
- 어느 세션을 이어받을지 모르면 `/history`로 Claude·Codex 로그를 읽기 전용 조회·검색한 뒤,
  선택한 경로를 `/fw --session`으로 넘긴다.
- 여러 라운드 PR 리뷰는 `/review-ledger`로 finding ID·상태·근거를 기록하고, 기존 open
  finding 재검수 후 신규 탐색 순서를 지킨다. 로컬 원장 요약은 handoff-save가 자동 포함한다.
- 버그 수정 테스트는 `/verify-regression`으로 수정 전 source에서도 실행해 실제 회귀 재현
  테스트와 신규 로직 가드를 구분하고, 결과를 PR 설명과 review-ledger evidence에 남긴다.
