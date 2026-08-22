# agent-harness

[![validate](https://github.com/foxyberry/agent-harness/actions/workflows/validate.yml/badge.svg)](https://github.com/foxyberry/agent-harness/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

*[English](README.md) · 한국어*

핸드오프, 공유 메모리, 회고, 리뷰·정리 워크플로를 **Claude Code 와 Codex 양쪽에** 배포하는
재사용 가능한 에이전트 하네스입니다. 다른 세션이나 다른 도구에서 작업을 이어받는 사람, 그리고
머지된 작업에서 얻은 교훈이 트랜스크립트와 함께 증발하지 않고 프로젝트 메모리로 남기를 바라는
사람을 위한 것입니다.

> 📖 **처음이거나 오랜만이라면 [사용 안내](docs/guide.md)부터 보세요.** 상황별로 무엇을 언제
> 쓰는지 정리돼 있습니다. 이 README 는 설치와 전체 구조를, 안내서는 실제 사용법을 다룹니다.

## 설치

### Claude Code

Claude Code 세션 안에서 실행합니다.

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

공개 marketplace 는 익명 HTTPS 로 설치됩니다 — 저장소 접근 권한이나 SSH 키가 필요 없습니다.

> **⚠️ Codex 훅은 신뢰해야 동작합니다.** Codex 는 신뢰하지 않은 훅을 **아무 메시지 없이
> 건너뜁니다.** 설치는 성공한 것처럼 보이는데 훅만 조용히 아무 일도 안 합니다.
>
> 설치 후 Codex 세션을 열면 `Hooks need review` 화면이 뜹니다. 훅을 확인하고 신뢰하면 됩니다.
> 나중에 `/hooks` 로 언제든 다시 볼 수 있고, `Active` 열이 `0` 이면 아직 안 도는 상태입니다.
> 플러그인 업데이트로 훅 내용이 바뀌면 Codex 가 다시 물어봅니다. 스킬만 쓸 거면 신뢰하지 않아도
> 됩니다. 자세한 내용은 [docs/codex-hooks.md](docs/codex-hooks.md).

## Claude Code 와 Codex

두 어댑터는 같은 `core/` 에서 만들어지지만 설치 방식과 호출 방식이 다릅니다.

### 플랫폼 차이

두 도구가 원래 다른 부분입니다. `core/` 를 복사하지 않고 어댑터별로 다시 포장해야 하는 이유입니다.

| | Claude Code | Codex |
|---|---|---|
| 스킬 호출 방식 | 슬래시 커맨드 (`/handoff-save`) | 모델이 스킬의 `description` 을 읽고 판단 |
| 스크립트 위치 | `bin/`, 플러그인 활성 시 `PATH` 등록 | 스킬마다 `scripts/` 에 번들 |
| 훅 신뢰 | 설치가 곧 동의 | **훅마다 따로 검토·신뢰**, 해시 기준이라 내용이 바뀌면 다시 물음 |
| 훅이 보는 편집 도구 | `Edit`, `Write`, `MultiEdit` | `apply_patch` — 여러 파일이 패치 하나에 |
| 훅의 프로젝트 경로 | `CLAUDE_PROJECT_DIR` | 안 줌. 훅 입력 JSON 의 `cwd` 사용 |
| 훅의 플러그인 경로 | `CLAUDE_PLUGIN_ROOT` | 같은 변수 (Codex 가 호환 별칭으로 제공) |
| 로컬 marketplace | `/plugin marketplace add ./` | `codex plugin marketplace add ./` |

Codex 는 `description` 을 읽고 스킬을 고르므로, Codex 를 향한 설명에는 **무엇을 하는지가 아니라
언제 쓰는지**를 적어야 합니다.

### 이식 진도 — 플랫폼 한계가 아님

| | Claude Code | Codex |
|---|---|---|
| 스킬 | 7 | 7 |
| 훅 | 4 | **4** (`pr-merge-reflect` 는 탐지/큐 단계) |

편집 훅은 이제 Codex 에서도 돕니다. Codex 는 편집을 파일 경로와 새 내용이 아니라 `apply_patch`
원문으로 넘겨서, 두 모양을 같은 모델로 바꾸는 정규화 단계를 뒀습니다. 머지 훅은 탐지와 공유
큐 갱신까지만 이식했고, 사용자 프롬프트 주입과 백그라운드 LLM 잡은 설치 smoke test 전까지
꺼 둡니다
([#85](https://github.com/foxyberry/agent-harness/issues/85)).

## 왜 만들었나

- 세션이 끝날 때 상태를 갈무리하는 데서 멈추지 않습니다. 편집 *전* 메모리를 넣어주는 것부터
  머지 *후* 회고를 재촉하는 것까지 하나의 루프로 이어집니다.
- 핸드오프와 메모리를 로컬 트랜스크립트가 아니라 Git 에 커밋합니다. 그래서 도구·머신·사람을
  건너 작업이 이어집니다.
- 자동으로 뽑힌 교훈은 바로 공유되지 않고 `_pending → 사람 승인 → committed` 를 거칩니다.

## 무엇이 들어 있나

| 스킬 | 하는 일 |
|---|---|
| `handoff-save` | 넘기기 전 현재 상태를 커밋 가능한 파일로 저장 |
| `handoff-load` | 커밋된 핸드오프를 읽고 현재 Git 상태와 대조해 작업 재개 |
| `fw` | 저장하지 못한 작업을 반대 도구의 로컬 세션 로그에서 복구 |
| `fw-both` | Claude 와 Codex 세션 로그를 함께 대조 |
| `history` | 로컬 세션을 시간순으로 조회·검색 |
| `feedback-review` | 리뷰 피드백을 프로젝트 규칙이나 스킬로 승격할지 검토 |
| `memory-update` | `_pending` 초안을 사람이 검토한 뒤 공유 메모리로 승격 |

## 자기개선 루프

명시적으로 부르는 스킬 외에, 훅이 알아서 발화하며 프로젝트 메모리를 사용합니다.

| 시점 | 훅 | 하는 일 | Claude | Codex |
|---|---|---|---|---|
| 세션 시작 | `project-memory-index` | `.claude/memory/INDEX.md` 를 컨텍스트에 주입 | ✅ | ✅ |
| 편집 전 | `memory-search` | 지금 건드리는 파일과 관련된 메모리 주입 | ✅ | ✅ |
| 편집 후 | `reflection` | 프로젝트 정규식 규칙과 TODO/FIXME 품질 경고 | ✅ | ✅ |
| 머지 후 | `pr-merge-reflect` | 미회고 PR 알림, 선택적으로 회고 초안 생성 | ✅ | 🟡 탐지/큐 등록, smoke 대기 |

Codex 는 마지막 훅을 SessionStart와 Bash PostToolUse 탐지에만 등록합니다. 사용자 프롬프트
전달과 자동 초안은 설치 smoke test 전까지 비활성입니다
([#85](https://github.com/foxyberry/agent-harness/issues/85)).

훅 엔진은 `core/` 에 있고 generic 합니다. *어떤* 메모리를 넣고 *어떤* 규칙을 검사할지는 프로젝트의
`.claude/memory/` 데이터가 정합니다. 데이터가 없으면 훅은 조용히 아무것도 안 합니다. 자동 회고는
`claude -p` 를 띄우므로 `HARNESS_AUTO_REFLECT=1` 을 켜기 전까지 실행되지 않습니다.

[훅 상세](docs/self-improvement-hooks.md) · [Codex 훅 제약](docs/codex-hooks.md)

## 프로젝트에 적용하기

플러그인은 공통 기능을 설치하고, `project-template/` 은 저장소별 규칙과 예시 데이터를 제공합니다.

1. `project-template/AGENTS.md` 를 프로젝트의 정본 규칙에 병합합니다.
2. Claude Code 를 쓴다면 `CLAUDE.md` 의 `@AGENTS.md` import 를 유지합니다.
3. `.claude/memory/` 의 route·reflection 예시를 프로젝트 기술 스택에 맞게 고칩니다.
4. `.github/` 의 PR 템플릿과 workflow 를 기존 CI 규칙과 병합합니다.

기존 파일을 통째로 덮어쓰지 마세요. `AGENTS.md`, `CLAUDE.md`, `.github/` 가 기존 규칙과 충돌할
가능성이 가장 큽니다.

## 구조

| 층 | 위치 | 역할 |
|---|---|---|
| core | `core/` | 툴 무관 정본: 스킬, 스크립트, 메모리·핸드오프 형식 |
| adapter | `plugins/harness/`, `plugins/codex/` | `core/` 를 Claude·Codex 배포 형식으로 포장 |
| opinion pack | `project-template/`, `docs/` | 선택적으로 채택하는 팀 워크플로와 예시 데이터 |

`core/` 가 정본이고 어댑터는 `build.sh` 가 만드는 **생성물**입니다. 어댑터를 직접 고치면 다음
빌드에서 덮이고, CI 가 그 차이를 잡아 실패시킵니다.

## 업데이트

```bash
# Claude Code
claude plugin marketplace update foxyberry

# Codex — 아직 `plugin update` 가 없어서 스냅샷을 갱신하고 다시 설치합니다
codex plugin marketplace upgrade foxyberry
codex plugin remove agent-harness@foxyberry
codex plugin add agent-harness@foxyberry
```

**Codex 세션을 먼저 닫으세요.** Codex 는 새 버전을 설치할 때 옛 버전 캐시 폴더를 지우는데,
이미 돌고 있던 세션은 지워진 경로를 계속 가리킵니다. 그러면 훅이 실패하고, Codex 를 재시작하기
전까지 **셸 명령을 아예 못 씁니다** — 2026-08-17 에 실제 `gh` 명령이 이렇게 거부됐습니다.
재시작하면 해소되고 잃는 건 없습니다. Claude Code 는 옛 버전 폴더를 남겨두므로 세션이
업데이트를 넘어 살아남습니다.

0.8.1 부터는 훅이 스스로 흡수하므로, 이 경고는 그 이전 버전에서 시작한 세션에 해당합니다.
자세한 내용은 [docs/codex-hooks.md](docs/codex-hooks.md) 에 있습니다.

자주 할 필요는 없습니다. 새 릴리스가 나왔을 때만 하면 됩니다.

## 개발

`core/` 를 고친 뒤에는 어댑터를 다시 생성합니다.

```bash
./build.sh
python3 -m unittest discover -s tests
```

CI 는 JSON 매니페스트 문법, Python 문법, 테스트, 그리고 `core/` 와 생성된 어댑터의 동기화를
검사합니다.

## 상태

- 플러그인 버전: `0.11.0`
- Claude Code·Codex 양쪽 공개 marketplace 설치 검증 완료
- 양쪽 어댑터에 스킬 7개, 크로스툴 핸드오프 검증 완료 (한쪽이 저장한 것을 다른 쪽이 로드)
- 훅 발화와 컨텍스트 주입 검증 완료 — 훅을 끈 세션과 켠 세션에 같은 질문을 던져, 모델이 파일을
  직접 읽어 답한 경우를 배제했습니다
- Codex 에는 훅 4개가 올라가 있고, `pr-merge-reflect` 는 설치 smoke test 전까지
  탐지/큐 단계만 등록됩니다

## 문서

| 문서 | 용도 |
|---|---|
| [docs/guide.md](docs/guide.md) | **여기서 시작** — 무엇을 언제 쓰나 |
| [docs/overview.html](docs/overview.html) | 그림이 있는 설계 개요 |
| [docs/self-improvement-hooks.md](docs/self-improvement-hooks.md) | 훅이 어떻게 도는지 |
| [docs/codex-hooks.md](docs/codex-hooks.md) | Codex 훅 계약과 제약 |
| [AGENTS.md](AGENTS.md) | 이 저장소 자체의 규칙 |

## 보안 · 라이선스 · 기여

- 보안 취약점은 공개 이슈가 아니라 [보안 정책](SECURITY.md)의 비공개 경로로 제보해 주세요.
- [MIT License](LICENSE)로 배포됩니다.
- 변경 제안은 이슈에서 먼저 논의한 뒤 PR 로 올려 주세요.
