# 프로젝트 메모리 인덱스 — agent-harness

공유(커밋) 메모리. Claude 는 memory-search 훅으로, Codex 는 이 인덱스로 읽는다.

- [engine-data-separation](engine-data-separation.md) — core/hooks는 generic 엔진, "무엇을"은 프로젝트 데이터. 하드코딩 금지
- [hooks-live-dir-gotcha](hooks-live-dir-gotcha.md) — 플러그인 dev설치(작업 repo 직접 참조); 훅 삭제 시 다른 세션 Bash 블록 주의
- [build-drift](build-drift.md) — core가 정본, core 수정 후 항상 ./build.sh 하고 생성물까지 커밋
- [plugin-release-updates](plugin-release-updates.md) — 사용자-facing 플러그인 배포는 버전 bump 와 업데이트 안내를 릴리스 단위로 관리
- [adapter-cross-project-testing](adapter-cross-project-testing.md) — 어댑터 동작은 harness repo 밖 별도 프로젝트에서 검증 (dev 설치가 버그 가림)
- [skill-command-examples](skill-command-examples.md) — SKILL.md 필수 인자는 각주 말고 복붙되는 명령 예시 자체에
