# CLAUDE.md

이 저장소의 지침 정본은 **[AGENTS.md](./AGENTS.md)** 다. 먼저 그걸 읽고 따른다.

@AGENTS.md

## Claude 전용 메모

- Claude Code 는 AGENTS.md 를 native 로 읽지 않으므로 이 포인터가 필요하다 (그래서 `@AGENTS.md` import).
- Claude 어댑터 = `plugins/harness/` (루트 `.claude-plugin/marketplace.json` 로 배포).
- 스킬·훅은 `core/` 가 정본 → `./build.sh` 로 `plugins/harness/` 에 복사 생성. 플러그인 폴더 안만 참조(`${CLAUDE_PLUGIN_ROOT}`), `../` 금지.
