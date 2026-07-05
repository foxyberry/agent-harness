# AGENTS.md — agent-harness

재사용 가능한 에이전트 하네스를 **Claude Code + Codex** 양쪽에 배포하는 저장소.
이 파일이 **정본(single source of truth)** 이다. Claude Code 는 `CLAUDE.md` 가 이 파일을 import 한다.

## 3층 구조 (핵심 설계)

- **core/** — 툴 무관 정본: Agent Skills(표준 `SKILL.md`), 공유 스크립트, 메모리 스키마, 핸드오프 포맷.
- **adapters** — core 를 각 툴로 포장:
  - `plugins/harness/` = Claude 플러그인 (루트 `.claude-plugin/marketplace.json` 로 배포)
  - `codex/` = Codex skill-only plugin + `config.toml` merge (검증 후 채움)
- **opinion pack** (`project-template/`, 문서) — 개인/팀 워크플로·커밋 규칙·회고 방식. 취향이라 분리해 선택 채택.

## 빌드

`core/` 를 정본으로 두고, 어댑터는 **복사 생성**한다(심링크 X — 크로스플랫폼·외부배포 안전).

```bash
./build.sh   # core/ → plugins/harness (Claude). 커밋 전 항상 실행.
```

## 배포 (비대칭 — 숨기지 말 것)

- **Claude**: `/plugin marketplace add foxyberry/agent-harness` → `/plugin install agent-harness@foxyberry`
- **Codex**: `./installers/install-codex.sh` (skill 설치 + `~/.codex/config.toml` merge)
- **공통**: 프로젝트에 `project-template/` 복사 (AGENTS.md 정본 + `.claude/memory` 템플릿)

설치 방식은 툴마다 다르지만 **사용자-facing 명령 이름은 통일**한다: `/handoff-save`, `/handoff-load`, `/feedback-review`, `/memory-update`.

## 규칙

- core 수정 → `build.sh` → 어댑터 재생성분까지 함께 커밋.
- 번들 스크립트는 어댑터 안에서 `${CLAUDE_PLUGIN_ROOT}`(Claude) 로만 참조, `../` 금지.
- 커밋 공유 메모리는 governance 필수: `_pending → 사람 승인 → committed`. 민감정보 금지.
