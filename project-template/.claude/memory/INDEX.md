# 프로젝트 메모리 인덱스

공유(커밋) 메모리 목록. Claude 는 세션 시작 시 이 인덱스를 자동으로 보고, 이후
memory-search 훅으로 관련 메모리 본문을 읽는다. **Codex 는 이 인덱스를 직접 읽는 것**을 기본으로 한다.
`/memory-update` 가 메모리 파일을 추가·갱신할 때 여기에 한 줄씩 등록한다.

- [code-quality](patterns/code-quality.md) — 코드 품질 규칙 (예시 — 교체하라)
- [git-workflow](decisions/git-workflow.md) — git 작업 규칙 (예시 — 교체하라)

설정 파일:
- `routes.json` — 편집 파일·셸 명령→메모리 주입 매핑
- `reflection-rules.json` — 편집 후 품질 경고 정규식
- `reflect-skip.json` — 회고 산출물 PR skip rule

## 결정 기록 (ADR — decisions/, 스키마는 decisions/README.md)
승격된 ADR 을 여기 한 줄씩 등록한다: `[<id>](decisions/<name>.md) — [chain: <chain>] <한 줄>`.
(형식 예시는 `decisions/adr-EXAMPLE-*.md` 참조 — 그 예시 파일은 실제 결정이 아니므로 이 목록에 넣지 않는다.)
