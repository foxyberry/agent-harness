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

## 메모리 (agent-harness)

- 공유 메모리는 `.claude/memory/` 에 **커밋**된다. 목록은 `.claude/memory/INDEX.md`.
- Claude 플러그인은 세션 시작 시 `INDEX.md` 를 자동으로 주입한다. Codex 는 아직 훅 배포가 없어
  작업 시작 시 이 인덱스를 직접 읽는 것을 기본 규칙으로 둔다.
- 훅 데이터: `routes.json`(편집 파일→메모리 주입), `reflection-rules.json`(품질 경고 정규식).
  이 프로젝트 언어·규칙에 맞게 고쳐 쓴다 — 없으면 훅은 조용히 no-op.
- governance: 자동 회고 초안은 `_pending/` 에만 쌓이고, `/memory-update` 로
  **사람 승인 후** 승격된다. 민감정보(키·토큰·내부 URL)는 메모리·핸드오프에 금지.

## 핸드오프

- 세션·툴(Codex↔Claude)·머신·사람을 바꾸기 전 `/handoff-save` — `.claude/handoff/<브랜치>.md` 로 커밋.
- 이어받을 때 `/handoff-load` — 커밋된 핸드오프 1순위, 현재 git 상태가 항상 우선.
