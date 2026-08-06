# agent-harness

[![validate](https://github.com/foxyberry/agent-harness/actions/workflows/validate.yml/badge.svg)](https://github.com/foxyberry/agent-harness/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Claude Code와 Codex에 핸드오프, 공유 메모리, 회고, 리뷰·정리 워크플로를 함께 배포하는
재사용 가능한 에이전트 하네스입니다. 작업을 다른 세션이나 도구에서 이어받고, 머지된 작업의
교훈을 프로젝트 메모리로 남기는 팀을 대상으로 합니다.

## 빠른 설치

### Claude Code

Claude Code 안에서 실행합니다.

```text
/plugin marketplace add foxyberry/agent-harness
/plugin install agent-harness@foxyberry
```

### Codex

터미널에서 실행합니다.

```bash
codex plugin marketplace add foxyberry/agent-harness
codex plugin add agent-harness@foxyberry
```

공개 marketplace는 별도 저장소 권한이나 SSH 인증 없이 HTTPS로 설치됩니다.

## Claude Code와 Codex

두 어댑터는 같은 core 스킬을 사용하지만 설치와 호출 방식은 다릅니다.

| | Claude Code | Codex |
|---|---|---|
| 배포 형태 | 플러그인 | skill-only 플러그인 |
| 호출 방식 | `/handoff-save` 같은 슬래시 커맨드 | skill description 매칭 |
| 자동 훅 | 자기개선 훅 제공 | 버전 안정성 문제로 보류 |
| 로컬 marketplace | `/plugin marketplace add ./` (저장소 루트) | `codex plugin marketplace add ./` (저장소 루트) |

사용자-facing 기능 이름은 같지만 Codex에서 슬래시 호출을 보장하지는 않습니다.

## 왜 agent-harness인가

- 세션 종료 시 기록하는 데 그치지 않고, 편집 전 메모리 주입부터 머지 후 회고까지 연결합니다.
- 로컬 transcript 대신 Git에 커밋되는 핸드오프와 메모리로 도구·사람·컴퓨터 사이에서 작업을 이어갑니다.
- 자동 생성된 교훈은 바로 공유하지 않고 `_pending → 사람 승인 → committed` 절차를 거칩니다.

## 주요 기능

| 기능 | 하는 일 |
|---|---|
| `handoff-save` | 넘기기 전 현재 작업 상태를 커밋 가능한 파일로 저장 |
| `handoff-load` | 커밋된 핸드오프와 현재 Git 상태를 대조해 작업 재개 |
| `fw` | 저장하지 못한 작업을 반대 도구의 로컬 세션 로그에서 복구 |
| `fw-both` | Claude와 Codex 양쪽 세션 로그를 함께 대조 |
| `history` | 로컬 세션을 시간순으로 조회·검색 |
| `feedback-review` | 리뷰 피드백을 프로젝트 규칙이나 스킬로 승격할지 검토 |
| `memory-update` | `_pending` 초안을 사람이 검토한 뒤 공유 메모리로 승격 |
| `merge-cleanup` | PR 머지 후 브랜치, 이슈, worktree와 임시 파일 정리 후보 제시 |
| `prettier-guard` | 기존부터 non-clean인 파일의 불필요한 전체 포맷 방지 |
| `review-ledger` | 여러 라운드의 PR 리뷰 finding과 반영 상태 추적 |
| `stale-scan` | 오래된 이슈를 코드와 머지된 PR 근거로 분류 |
| `verify-regression` | 새 테스트를 수정 전 source에서 실행해 실제 회귀인지 검증 |

## 자기개선 루프

Claude 어댑터는 명시적으로 실행하는 기능 외에도 프로젝트 메모리를 활용하는 훅을 제공합니다.

| 시점 | 훅 | 동작 |
|---|---|---|
| 세션 시작 | `project-memory-index` | `.claude/memory/INDEX.md`를 컨텍스트에 주입 |
| 편집 전 | `memory-search` | 수정 파일과 관련된 프로젝트 메모리 주입 |
| 편집 후 | `reflection` | 프로젝트 정규식 규칙과 TODO/FIXME 품질 경고 |
| 머지 후 | `pr-merge-reflect` | 미회고 PR 알림과 선택적 회고 초안 생성 |

훅 엔진은 `core/`에 있고, 어떤 메모리를 주입하고 어떤 규칙을 검사할지는 프로젝트의
`.claude/memory/` 데이터가 결정합니다. 데이터가 없으면 조용히 no-op하며, `claude -p`를 사용하는
자동 회고는 `HARNESS_AUTO_REFLECT=1`로 명시적으로 켜기 전까지 실행되지 않습니다.

[자기개선 훅 상세 문서](docs/self-improvement-hooks.md)

## 프로젝트에 적용

플러그인은 공통 기능을 설치하고, `project-template/`은 저장소별 운영 규칙을 제공합니다.

1. `project-template/AGENTS.md`를 프로젝트 규칙의 정본으로 병합합니다.
2. Claude Code를 사용한다면 `CLAUDE.md`의 `@AGENTS.md` 연결을 유지합니다.
3. `.claude/memory/`의 route와 reflection 예시를 프로젝트 기술 스택에 맞게 수정합니다.
4. `.github/`의 PR 템플릿과 workflow를 기존 CI 규칙과 병합합니다.

기존 파일을 통째로 덮어쓰지 마세요. 특히 `AGENTS.md`, `CLAUDE.md`, `.github/`는 프로젝트의
기존 규칙과 충돌할 수 있습니다.

## 구조

| 층 | 위치 | 역할 |
|---|---|---|
| core | `core/` | 툴 무관 정본: Agent Skills, 스크립트, 메모리·핸드오프 형식 |
| adapter | `plugins/harness/`, `plugins/codex/` | core를 Claude와 Codex 배포 형식으로 포장 |
| opinion pack | `project-template/`, `docs/` | 선택적으로 채택하는 팀 워크플로와 예시 데이터 |

`core/`가 정본이고 어댑터는 `build.sh`로 복사 생성됩니다.

## 업데이트

Claude Code에서는 marketplace의 플러그인 관리 화면을 사용합니다. Codex는 새 릴리스가 필요할 때
marketplace snapshot과 설치 캐시를 갱신합니다.

```bash
codex plugin marketplace upgrade foxyberry
codex plugin remove agent-harness@foxyberry
codex plugin add agent-harness@foxyberry
```

## 개발

core를 수정한 뒤 반드시 어댑터를 재생성합니다.

```bash
./build.sh
python3 -m unittest discover -s tests
```

CI는 JSON과 Python 문법, 테스트, core와 adapter의 동기화를 검사합니다.

## 상태

- 현재 플러그인 버전: `0.4.11`
- Claude Code와 Codex 공개 marketplace 설치 검증 완료
- 양쪽 어댑터에 스킬 12개 배포 및 크로스툴 handoff 검증 완료
- Claude 훅 이벤트 인식과 설치 캐시 실행 검증 완료
- Claude 훅의 실제 발화·컨텍스트 주입 검증은 진행 중
- Codex 자동 훅은 upstream 버전 안정성 문제로 보류

시각 자료가 포함된 상세 개요는 [`docs/overview.html`](docs/overview.html), 설계 문서는
[`docs/`](docs/)에서 확인할 수 있습니다.

## 보안 · 라이선스 · 기여

- 보안 취약점은 공개 이슈 대신 [보안 정책](SECURITY.md)의 비공개 신고 경로로 제보해 주세요.
- 이 프로젝트는 [MIT License](LICENSE)로 배포됩니다.
- 변경 제안은 이슈에서 먼저 논의한 뒤 PR로 제출해 주세요.
