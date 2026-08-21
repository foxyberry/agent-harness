# AGENTS.md — agent-harness

재사용 가능한 에이전트 하네스를 **Claude Code + Codex** 양쪽에 배포하는 저장소.
이 파일이 **정본(single source of truth)** 이다. Claude Code 는 `CLAUDE.md` 가 이 파일을 import 한다.

## 3층 구조 (핵심 설계)

- **core/** — 툴 무관 정본: Agent Skills(표준 `SKILL.md`), 자기개선 훅(`core/hooks/`), 공유 스크립트, 메모리 스키마, 핸드오프 포맷.
- **adapters** — core 를 각 툴로 포장:
  - `plugins/harness/` = Claude 플러그인 (루트 `.claude-plugin/marketplace.json` 로 배포)
  - `plugins/codex/` = Codex skill-only plugin (`.agents/plugins/marketplace.json` 로 배포)
- **opinion pack** (`project-template/`, 문서) — 개인/팀 워크플로·커밋 규칙·회고 방식 + **훅 데이터**(`routes.json`·`reflection-rules.json`). 취향이라 분리해 선택 채택.

## 자기개선 훅 루프 (엔진=core, 데이터=프로젝트)

이 하네스의 차별점은 스킬 위의 **자기개선 루프**다: project-memory-index(세션 시작 시 공유 메모리 목록 주입)
→ memory-search(편집 전 관련 메모리 주입) → reflection(편집 후 품질 경고) → pr-merge-reflect(머지 시 회고) → `/memory-update` 승격.

- **엔진**(`core/hooks/`)은 툴 무관·generic. "무엇을" 주입·경고할지는 하드코딩하지 않는다.
- **데이터**는 프로젝트의 `.claude/memory/` 에 산다: `routes.json`(파일·셸 명령→메모리 매핑),
  `reflection-rules.json`(정규식 품질 규칙), `reflect-skip.json`(회고 PR 예외 규칙).
  없으면 훅은 조용히 no-op(내장 TODO/FIXME·기본 회고 skip rule 만).
  예시 데이터는 `project-template/.claude/memory/` 에.
- **훅은 Claude 전량 + Codex 일부** 배포. 양쪽 다 `hooks/hooks.json` 과 `${CLAUDE_PLUGIN_ROOT}` 를 쓴다
  — Codex 도 이 변수를 **호환 별칭으로 세팅해 준다**(0.145.0 실측). Codex 는 매니페스트에
  `"hooks": "./hooks/hooks.json"` 키로 등록한다. Codex 에는 네 훅을 번들하지만,
  `pr-merge-reflect` 는 SessionStart·PostToolUse 탐지/큐 단계만 올렸다. UserPromptSubmit 리마인더와
  자동 LLM 회고는 설치 실측 전까지 보류한다. 자세한 제약과 이식 상태는 `docs/codex-hooks.md`.
- **자동 회고 잡**(`reflect.py` 가 `claude -p` 로 초안 생성)은 **기본 꺼짐**. 설치만으로
  백그라운드 LLM 잡이 뜨지 않게 `HARNESS_AUTO_REFLECT=1` opt-in 뒤에 게이트. 리마인더는 항상 켜짐.
- 경로 규약: **스크립트**는 `${CLAUDE_PLUGIN_ROOT}`(플러그인 루트, co-located),
  **데이터**는 `$CLAUDE_PROJECT_DIR`(프로젝트 루트). 플러그인에선 이 둘이 갈린다 — 혼동 금지.

## 빌드

`core/` 를 정본으로 두고, 어댑터는 **복사 생성**한다(심링크 X — 크로스플랫폼·외부배포 안전).

```bash
./build.sh   # core/ → plugins/harness (Claude) + plugins/codex (Codex). 커밋 전 항상 실행.
```

## 배포 (비대칭 — 숨기지 말 것)

- **Claude**: `/plugin marketplace add foxyberry/agent-harness` → `/plugin install agent-harness@foxyberry`
- **Codex**: `codex plugin marketplace add foxyberry/agent-harness` / 로컬 `codex plugin marketplace add ./`. 별도 installer 없이 공식 marketplace CLI가 설치·업데이트·캐시를 관리한다.
- **공통**: 프로젝트에 `project-template/` 복사 (AGENTS.md 정본 + `.claude/memory` 템플릿)

설치 방식은 툴마다 다르지만 **사용자-facing 명령 이름은 통일**한다: `/handoff-save`, `/handoff-load`, `/fw`, `/fw-both`, `/history`, `/feedback-review`, `/memory-update`.

**handoff vs fw vs fw-both**: `handoff-save/load` = 사람이 명시적으로 커밋하는 이식 정본(크로스머신). `fw` = 저장 안 했어도 세션 로그(Claude `.jsonl`/Codex rollout)에서 자동 복원하는 보조(같은 머신, 툴 전환용). 렌더된 `fw` 는 **반대 툴**을 `--from` 기본값으로 넘겨 현재 세션 자기선택을 막는다. `fw-both` = **Claude·Codex 양쪽 로그를 한 번에** 보는 변형(`fw --from both`) — 여러 툴에 작업이 흩어졌을 때 합쳐서 이어받는다. 렌더된 `fw-both` 는 `--current <현재툴>`(빌드 시 어댑터별로 claude/codex 렌더)을 넘겨 **현재 툴의 live 세션만** 배제(반대 툴 최신은 진짜 직전 작업이라 유지). 셋 다 **현재 git 이 우선**.

`history`는 복원하지 않는 읽기 전용 탐색 계층이다. Claude·Codex 로그를 목록·검색하고
선택한 로그 경로를 `fw --session`에 넘긴다.

### 업데이트/릴리스 운영

- 일반 사용자는 자주 업데이트하지 않게 한다. 로컬 dogfooding 과 사용자-facing 릴리스를 분리한다.
- 사용자-facing 변경을 배포할 때는 `plugins/codex/.codex-plugin/plugin.json`과
  `plugins/harness/.claude-plugin/plugin.json` 버전을 **같이** 올린다(같은 버전 유지,
  버전 그대로 캐시 갱신 요구 금지).
- Codex 는 현재 `plugin update` 가 없으므로 업데이트 안내는 `marketplace upgrade` 후 `remove`/`add` 로 캐시를 새로 받는 방식이다.
- 로컬 개발 검증은 `./build.sh` → `codex plugin marketplace add ./` → `codex plugin remove/add agent-harness@foxyberry` 로 한다.
- **업데이트 안내에는 "Codex 세션을 먼저 닫아라"를 함께 적는다.** Codex 는 새 버전을 깔 때
  옛 버전 캐시 폴더를 지우고, 돌고 있던 세션은 지워진 경로를 계속 가리켜 셸 명령을 못 쓰게
  된다(재시작하면 해소, 무손실). Claude 는 옛 버전을 보관해 해당 없다. 0.8.1 부터 훅이
  스스로 흡수하지만, 그 이전 버전에서 시작한 세션에는 여전히 해당한다 → `docs/codex-hooks.md`.
- README 에는 사용자 설치/업데이트 명령만 짧게 유지하고, 절차가 길어지면 `docs/release.md` 로 분리한다.

## 무엇이 이 하네스에 속하나 (2026-08-17)

새 스킬·도구를 여기 넣을지 판단하는 기준:

> **에이전트가 만들어낸 상태(세션 로그·메모리·훅)를 다루면 여기 남는다.
> git·GitHub 만 다루면 일반 도구이므로 개인 `~/.claude/skills/` 나 다른 저장소로 간다.**

이 하네스의 목적은 둘뿐이다 — 세션·툴·머신을 넘어 **작업을 이어받게** 하는 것, 머지된
작업의 **교훈이 메모리로 살아남게** 하는 것. 둘 중 어디에도 안 들어가면 쓸모와 무관하게
범위 밖이다.

실제로 한 번 넘쳤다. 2026-08-17 에 스킬 5개(`merge-cleanup`·`prettier-guard`·`stale-scan`
·`review-ledger`·`verify-regression`)를 개인 스코프로 내보냈다(#105). 셋째 축("점검")을
두었더니 브랜치 정리·이슈 점검 같은 일반 git 작업이 계속 쌓였고, 저장소 유지비의 대부분을
그쪽이 먹고 있었다. **축은 둘로 유지한다.**

경계선이 애매하면 예외를 만들지 말고 내보낸다. 예외를 하나 두면 선이 다시 흐려진다.

## 규칙

- core 수정 → `build.sh` → 어댑터 재생성분까지 함께 커밋.
- 번들 스크립트는 어댑터 안에서 `${CLAUDE_PLUGIN_ROOT}`(Claude) 로만 참조, `../` 금지.
- 커밋 공유 메모리는 governance 필수: `_pending → 사람 승인 → committed`. 민감정보 금지.
- **메모리 tier 판단 — 기본은 개인이다.** 이 저장소는 **공개**라 `.claude/memory/` 에 넣은 건
  전 세계에 공개된다. 공유(커밋)로 올리는 건 아래 둘 중 하나에 해당할 때만:
  - **Codex 가 이 저장소 코드를 고칠 때 알아야 하는 것** (Codex 는 Claude auto-memory 를 못 읽는다)
  - 이 하네스를 쓰는 **외부 사용자에게 참고가 되는 것**

  내 작업 습관·보고 방식·실수 이력은 **개인 tier**(`~/.claude/projects/.../memory/`)로 간다.
  공유 tier 는 PR·리뷰·머지 사이클이 붙으므로 값어치가 그 비용을 넘을 때만 쓴다.
- 교차검토가 필요한 작업은 **Claude Code 1차 검토 → Codex 사실·실행 교차검증** 순서로 진행한다.
- 외부 검토 결과는 로컬 보고로 끝내지 않고 대상 PR·이슈 댓글에 남긴다. 다른 스레드에 기록했다면
  대상 본문이나 댓글에서 원문을 링크한다.
