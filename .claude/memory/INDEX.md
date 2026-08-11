# 프로젝트 메모리 인덱스 — agent-harness

공유(커밋) 메모리. Claude 는 세션 시작 시 이 인덱스를 자동으로 보고, 이후 memory-search 훅으로
관련 메모리 본문을 읽는다. Codex 는 아직 훅 배포가 없어 이 인덱스를 직접 읽는다.

- [engine-data-separation](engine-data-separation.md) — core/hooks는 generic 엔진, "무엇을"은 프로젝트 데이터. 하드코딩 금지
- [hooks-live-dir-gotcha](hooks-live-dir-gotcha.md) — 플러그인 dev설치(작업 repo 직접 참조); 훅 삭제 시 다른 세션 Bash 블록 주의
- [build-drift](build-drift.md) — core가 정본, core 수정 후 항상 ./build.sh 하고 생성물까지 커밋
- [plugin-release-updates](plugin-release-updates.md) — 사용자-facing 플러그인 배포는 버전 bump 와 업데이트 안내를 릴리스 단위로 관리
- [adapter-cross-project-testing](adapter-cross-project-testing.md) — 어댑터 동작과 공개 설치는 repo·인증·캐시를 격리해 검증
- [skill-command-examples](skill-command-examples.md) — SKILL.md 필수 인자는 각주 말고 복붙되는 명령 예시 자체에
- [tool-placement-heuristic](tool-placement-heuristic.md) — 새 훅·도구 배치: 범용이면 하네스 core / 취향이면 개인 ~/.claude 또는 repo 커밋; 훅은 core 에 넣지 말 것
- [review-evidence-on-target-thread](review-evidence-on-target-thread.md) — 외부 리뷰 결과는 대상 PR·이슈 댓글에 원문 또는 링크로 남김
- [committed-artifact-env-leak](committed-artifact-env-leak.md) — 커밋되는 산출물에 호스트명·절대경로 자동 삽입 금지; 기본 비공개 + 환경변수 opt-in
- [squash-merge-consequences](squash-merge-consequences.md) — squash merge라 branch --merged 무력화; stacked PR은 base 머지 후 rebase
- [cache-must-outlive-target](cache-must-outlive-target.md) — 캐시·alias 저장 위치: worktree/세션 안에 두지 말 것, worktree 상태는 .git 공통 디렉터리에
- [docs-one-fact-one-place](docs-one-fact-one-place.md) — 같은 사실을 문서 여러 곳에 쓰지 말 것; 고치기 전에 grep 으로 사본 확인

## 결정 기록 (ADR)

승격된 ADR 을 한 줄씩 등록한다: `[<id>](decisions/<name>.md) — [chain: <chain>] <한 줄>`.
(스키마는 `project-template/.claude/memory/decisions/README.md`. 아직 승격된 실 ADR 없음.)
