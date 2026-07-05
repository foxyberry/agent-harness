# agent-harness

**Claude Code + Codex** 를 위한 재사용 가능한 에이전트 하네스.
핸드오프, 자기개선 회고, 커밋되어 공유되는 메모리, 워크플로 스킬을 한 번에 배포한다.

> 설치 방식은 툴마다 다르지만(**아래 비대칭 참고**), 설치 후 쓰는 **명령 이름은 동일**하다:
> `/handoff-save` · `/handoff-load` · `/feedback-review` · `/memory-update`

## 왜 다른가 (차별점)

공개 하네스 대부분은 *세션 종료 시 캡처*까지만 한다. 이 하네스는:
- **PR 머지 트리거 회고** — 세션 끝이 아니라 작업이 머지될 때 교훈을 남긴다.
- **커밋되어 크로스머신/툴 공유되는 메모리** — transcript(로컬·툴 종속) 대신 git 에 커밋되는 메모리·핸드오프로 다른 머신·사람·툴이 이어받는다.
- **governance 내장** — `_pending → 사람 승인 → committed`. 잘못된 교훈·민감정보가 자동으로 박히지 않는다.

## 설치 (비대칭 — 툴마다 다름)

### Claude Code (플러그인 한 방)
```
/plugin marketplace add foxyberry/agent-harness
/plugin install agent-harness@foxyberry
```
로컬 테스트: `/plugin marketplace add ./` (repo 루트에서)

### Codex (skill 설치 + config merge) — *검증 후 확정*
```
./installers/install-codex.sh
```

### 공통 (프로젝트 층)
프로젝트 repo 에 `project-template/` 를 복사 — `AGENTS.md`(정본) + `CLAUDE.md`(@import) + `.claude/memory/` 템플릿.

## 구조 (3층)

| 층 | 위치 | 내용 |
|----|------|------|
| **core** | `core/` | 툴 무관 정본 — Agent Skills(`SKILL.md`), 스크립트, 메모리 스키마, 핸드오프 포맷 |
| **adapter** | `plugins/harness/` (Claude), `codex/` (Codex) | core 를 각 툴로 포장 (build.sh 로 **복사 생성**) |
| **opinion pack** | `project-template/`, 문서 | 개인/팀 워크플로·회고 방식 (취향 — 선택 채택) |

`core/` 가 정본이고 어댑터는 생성물이다. 수정은 core 에서 → `./build.sh` → 어댑터 재생성.

## 명령 (설치 후)

| 명령 | 하는 일 |
|------|---------|
| `/handoff-save` | 넘기기 전 이식 가능한 상태를 커밋 파일로 저장 |
| `/handoff-load` | 이어받기 — 커밋된 핸드오프 1순위 + 현재 git 대조 |
| `/feedback-review` | 받은 지적을 규칙/스킬로 승격 검토 |
| `/memory-update` | 배운 것을 공유 메모리로 영속화 (`_pending` 검토·승격) |

## 개발

```bash
./build.sh    # core → 어댑터 재생성. 커밋 전 항상.
```
CI(`.github/workflows/validate.yml`)가 JSON·스크립트 문법 + **core↔adapter 동기화**(build.sh 안 돌린 채 커밋 방지)를 검증한다.

## 상태

구축 중. Claude 어댑터 + handoff 스킬부터 동작. Codex 어댑터·자기개선 훅·installer 는 진행 중.
